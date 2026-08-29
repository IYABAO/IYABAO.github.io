---
title: "第三方 API 集成中的稳定性保障：短信/邮件/Facebook 登录的高可用设计"
date: 2019-12-18T15:00:00+08:00
draft: false
tags: ["架构设计", "高可用", "第三方API", "短信", "邮件", "Facebook登录"]
categories: ["架构设计"]
summary: "跨境电商平台第三方 API 集成的稳定性保障实践，涵盖短信、邮件、Facebook 登录等核心外部依赖的降级、重试、熔断与监控方案。"
---

做跨境电商的时候，系统集成了大量第三方 API：短信验证码、邮件通知、Facebook 登录、支付接口、物流追踪等等。这些外部依赖不可控，接口超时、服务宕机、限流封禁都是家常便饭。如果不做好稳定性保障，第三方出问题就会拖垮自己的系统。

今天把我们在第三方 API 集成中的稳定性保障方案整理出来，核心思路就四个字：**解耦、降级**。

## 一、问题背景

跨境电商平台面向俄罗斯和东欧市场，核心外部依赖包括：

| 服务 | 提供商 | 用途 | 可用性要求 |
|------|--------|------|-----------|
| 短信 | SMSC.ru、Twilio | 验证码、通知 | 高（登录依赖） |
| 邮件 | SendGrid、SES | 注册确认、订单通知 | 中（可延迟） |
| 社交登录 | Facebook、VK | 第三方登录 | 中（有备用登录方式） |
| 支付 | Yandex.Checkout、PayPal | 支付收款 | 极高（核心链路） |
| 物流 | 俄罗斯邮政、CDEK | 物流追踪 | 低（可异步） |

这些第三方服务的 SLA 参差不齐，有的号称 99.9%，实际经常抽风。尤其是俄罗斯的本地服务，网络不稳定是常态。

## 二、核心设计原则

### 2.1 同步转异步

非核心链路的第三方调用，一律异步化。用户下单后发邮件、发短信、推物流信息，这些操作不应该阻塞下单流程。

用消息队列解耦：

```text
用户请求 → 业务处理 → 发消息到队列 → 返回成功
                              ↓
                        消费者异步调用第三方 API
```

这样第三方 API 慢或者挂了，不影响主流程。消费者可以慢慢重试，直到成功。

### 2.2 多提供商冗余

关键服务至少接两个提供商，主提供商挂了自动切到备用。短信和邮件都做了双提供商：

- 短信：主用 SMSC.ru（俄罗斯本地，到达率高），备用 Twilio（全球服务，稳定但贵）
- 邮件：主用 SendGrid，备用 AWS SES

### 2.3 超时与重试

所有第三方调用必须设置超时时间，不能无限等待。失败后根据错误类型决定是否重试：

- 网络超时、5xx 错误：可以重试
- 4xx 错误（参数错误、鉴权失败）：不要重试，重试也没用
- 限流错误（429）：退避后重试

重试策略用指数退避，避免雪崩：第1次等1秒，第2次等2秒，第3次等4秒，最多重试3次。

### 2.4 熔断降级

连续失败达到阈值后触发熔断，一段时间内不再调用该提供商，直接走备用或返回降级结果。熔断恢复用半开模式：放少量请求试探，成功了就关闭熔断，失败了继续熔断。

## 三、具体实现

### 3.1 统一的 API 客户端封装

所有第三方 API 调用都走统一的客户端基类，封装超时、重试、熔断、日志、监控：

```php
abstract class BaseApiClient
{
    protected $timeout = 5; // 超时5秒
    protected $retryTimes = 3; // 重试3次
    protected $retryDelay = 1; // 初始退避1秒
    protected $circuitBreaker; // 熔断器

    public function request($method, $url, $params = [])
    {
        // 熔断检查
        if ($this->circuitBreaker->isOpen()) {
            throw new CircuitOpenException('熔断器已打开');
        }

        $attempt = 0;
        $lastException = null;

        while ($attempt < $this->retryTimes) {
            try {
                $response = $this->doRequest($method, $url, $params);
                $this->circuitBreaker->recordSuccess();
                return $response;
            } catch (RetryableException $e) {
                // 可重试错误
                $lastException = $e;
                $attempt++;
                if ($attempt < $this->retryTimes) {
                    $delay = $this->retryDelay * pow(2, $attempt - 1);
                    usleep($delay * 1000000);
                }
            } catch (NonRetryableException $e) {
                // 不可重试错误，直接抛
                $this->circuitBreaker->recordFailure();
                throw $e;
            }
        }

        $this->circuitBreaker->recordFailure();
        throw $lastException;
    }

    abstract protected function doRequest($method, $url, $params);
}
```

### 3.2 熔断器实现

简单的熔断器实现，用 Redis 存储状态：

```php
class CircuitBreaker
{
    private $redis;
    private $key;
    private $failureThreshold = 10; // 连续失败10次熔断
    private $recoveryTime = 60; // 60秒后半开试探

    public function __construct($name)
    {
        $this->redis = Yii::$app->redis;
        $this->key = "circuit:{$name}";
    }

    public function isOpen()
    {
        $state = $this->redis->hget($this->key, 'state');
        if ($state === 'open') {
            $lastFailure = $this->redis->hget($this->key, 'last_failure');
            if (time() - $lastFailure > $this->recoveryTime) {
                // 半开状态，允许试探
                $this->redis->hset($this->key, 'state', 'half_open');
                return false;
            }
            return true;
        }
        return false;
    }

    public function recordSuccess()
    {
        $this->redis->hset($this->key, 'failures', 0);
        $this->redis->hset($this->key, 'state', 'closed');
    }

    public function recordFailure()
    {
        $failures = $this->redis->hincrby($this->key, 'failures', 1);
        $this->redis->hset($this->key, 'last_failure', time());

        $state = $this->redis->hget($this->key, 'state');
        if ($state === 'half_open') {
            // 半开状态失败，重新熔断
            $this->redis->hset($this->key, 'state', 'open');
        } elseif ($failures >= $this->failureThreshold) {
            $this->redis->hset($this->key, 'state', 'open');
        }
    }
}
```

### 3.3 短信服务多提供商切换

短信服务是关键链路（用户登录收验证码），必须做高可用：

```php
class SmsService
{
    private $providers = ['smsc', 'twilio'];
    private $currentProvider;

    public function send($phone, $message)
    {
        foreach ($this->providers as $provider) {
            try {
                $client = $this->getClient($provider);
                $client->send($phone, $message);
                $this->currentProvider = $provider;
                $this->logSuccess($provider, $phone);
                return true;
            } catch (Exception $e) {
                $this->logFailure($provider, $phone, $e->getMessage());
                continue; // 换下一个提供商
            }
        }
        throw new SmsException('所有短信提供商都失败了');
    }

    private function getClient($provider)
    {
        $clients = [
            'smsc' => new SmscClient(),
            'twilio' => new TwilioClient(),
        ];
        return $clients[$provider];
    }
}
```

每个客户端内部有自己的熔断器。主提供商熔断后，请求会直接走备用提供商，不会等超时。

### 3.4 邮件异步队列

邮件不要求实时，用队列异步发送：

```php
// 业务代码里只发消息，不直接调用邮件API
Yii::$app->queue->push(new SendEmailJob([
    'to' => $user->email,
    'subject' => '订单确认',
    'template' => 'order_confirm',
    'data' => ['order_id' => $order->id],
]));

// 消费者
class SendEmailJob extends BaseJob
{
    public function execute($queue)
    {
        $mailer = new MailService();
        $mailer->send($this->to, $this->subject, $this->template, $this->data);
    }
}
```

队列用 Redis 实现，消费者失败后消息会重新入队，自动重试。邮件发送失败也不影响业务，用户晚点收到邮件没关系。

### 3.5 Facebook 登录降级

第三方登录做降级方案：Facebook 登录失败时，提示用户用邮箱注册登录，不让用户卡在登录页。

```php
public function actionFacebookLogin()
{
    $code = Yii::$app->request->get('code');
    try {
        $facebook = new FacebookClient();
        $userInfo = $facebook->getUserInfo($code);
        // 登录或注册逻辑
        return $this->loginOrRegister($userInfo);
    } catch (Exception $e) {
        // Facebook 登录失败，降级到邮箱登录
        Yii::$app->session->setFlash('error', 'Facebook 登录暂时不可用，请使用邮箱登录');
        return $this->redirect(['site/login']);
    }
}
```

## 四、监控与告警

第三方 API 的稳定性，监控是关键。出了问题要第一时间知道，不能等用户反馈。

### 4.1 调用日志

所有第三方 API 调用都记录日志，包括：
- 调用时间
- 提供商、接口名
- 请求参数（脱敏）
- 响应状态、响应时间
- 错误信息

日志存到 Elasticsearch，用 Kibana 做可视化。可以按提供商、接口、错误码维度统计成功率和响应时间。

### 4.2 核心指标告警

设置告警规则：
- 单接口错误率 > 5%，持续 5 分钟 → 告警
- 单接口平均响应时间 > 3 秒，持续 5 分钟 → 告警
- 熔断器打开 → 立即告警
- 队列积压 > 1000 条 → 告警

告警通道：钉钉群机器人 + 邮件。严重问题直接打电话。

### 4.3 提供商健康看板

做了个简单的健康看板，实时展示每个第三方提供商的状态：

```text
提供商        成功率    平均响应时间    状态    熔断
SMSC.ru       98.5%     800ms          正常    关闭
Twilio        99.9%     1200ms         正常    关闭
SendGrid      99.2%     1500ms         正常    关闭
Facebook      97.8%     2000ms         注意    关闭
```

运维和开发都能看到，出问题一目了然。

## 五、踩过的坑

**1. 重试风暴**

有一次短信主提供商挂了，所有请求都切到备用提供商，备用提供商被瞬间打满，触发限流，然后也挂了。两个都挂了，短信完全发不出去。

教训：切换备用提供商的时候要限流，不能把所有流量瞬间打过去。加个速率限制，慢慢切过去。

**2. 重试导致重复发送**

短信接口超时了，但实际上服务商已经收到请求并发送了。我们重试了一次，用户收到了两条验证码。

教训：短信发送要做幂等，同一个手机号 + 同一个模板 + 1分钟内，只发一次。用 Redis 记录发送记录，重复请求直接返回成功。

**3. 第三方接口变更不通知**

Facebook 的 API 升级了，旧接口返回格式变了，我们的解析代码报错，登录功能挂了半天才发现。

教训：第三方 API 的响应解析要做容错，不能假设字段一定存在。关键接口加监控，错误率异常立即告警。

**4. DNS 缓存导致切不过去**

主提供商域名解析到了一个挂掉的 IP，DNS 缓存没过期，即使切到备用提供商的逻辑执行了，请求还是发到了挂掉的 IP。

教训：HTTP 客户端要设置 DNS 缓存时间，或者用 IP 直连 + Host 头的方式，避免 DNS 缓存问题。

**5. 证书过期**

有个第三方 API 的 SSL 证书过期了，我们的 HTTP 客户端校验证书，所有请求都失败。临时关闭了证书校验才恢复。

教训：监控第三方 API 的 SSL 证书有效期，提前告警。或者用不校验证书的方式（但有安全风险，不推荐）。

## 六、总结

第三方 API 集成的稳定性保障，核心是几个层次：

1. **异步化**：非核心链路全部走队列，解耦第三方依赖
2. **多提供商**：关键服务至少两个提供商，自动切换
3. **超时重试**：合理设置超时，可重试错误用指数退避重试
4. **熔断降级**：连续失败自动熔断，走备用或降级方案
5. **监控告警**：全链路日志 + 核心指标告警，出问题第一时间知道
6. **幂等设计**：重试场景下保证不重复执行

这些方案不是孤立的，要组合使用。异步化解决主流程不被阻塞，多提供商解决单点故障，超时重试解决偶发失败，熔断解决持续故障，监控解决发现问题，幂等解决重试副作用。

做第三方集成，心态要摆正：**所有外部依赖都是不可靠的，随时可能挂**。在这个前提下做设计，系统才能真正稳定。我们的系统现在第三方 API 出问题，用户基本感知不到，该发的短信晚点会到，该收的邮件不会丢，登录也有备用方式。这就是稳定性保障的价值。
