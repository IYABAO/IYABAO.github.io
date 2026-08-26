---
title: "Yii2.0 框架下微信公众号自动授权登录与会员卡体系落地实践"
date: 2019-03-15T10:30:00+08:00
draft: false
tags: ["PHP", "Yii2", "微信公众号", "微信支付", "会员卡"]
categories: ["PHP开发"]
summary: "基于 Yii2.0 框架搭建微信公众号自动授权登录与会员卡充值消费闭环，从 OAuth2.0 授权到微信支付统一下单的完整链路实践。"
---

去年接了个本地生活服务的项目，上门洗车加社区便利店，全部走微信公众号。老板的需求很明确：用户关注公众号后自动登录，不需要手动注册；会员卡体系要支持充值和消费，资金闭环在微信生态内完成。

整个项目用 Yii2.0 搭的，跑在阿里云主机上，Apache + MySQL。今天把这套方案的核心实现整理出来，给有类似需求的朋友做个参考。

## 一、微信公众号自动授权登录

微信公众号授权登录走的是 OAuth2.0 协议，分两种 scope：`snsapi_base`（静默授权，只拿 openid）和 `snsapi_userinfo`（弹窗授权，拿用户昵称头像）。

我们的场景是关注后自动登录，所以用 `snsapi_base` 就够了。用户关注公众号后，菜单链接直接带授权参数，微信回调回来带上 code，后端用 code 换 access_token 和 openid。

### 1.1 授权入口配置

公众号后台的网页授权域名要先配好，这个是基础，不配的话授权会报 redirect_uri 参数错误。

Yii2 里我写了一个 `WechatController`，专门处理微信相关的回调：

```php
class WechatController extends Controller
{
    public $enableCsrfValidation = false;

    // 授权入口
    public function actionAuth()
    {
        $appId = Yii::$app->params['wechat']['appId'];
        $redirectUri = urlencode('https://your-domain.com/wechat/callback');
        $state = Yii::$app->security->generateRandomString(16);
        Yii::$app->session->set('oauth_state', $state);

        $url = "https://open.weixin.qq.com/connect/oauth2/authorize"
             . "?appid={$appId}"
             . "&redirect_uri={$redirectUri}"
             . "&response_type=code"
             . "&scope=snsapi_base"
             . "&state={$state}"
             . "#wechat_redirect";

        return $this->redirect($url);
    }
}
```

### 1.2 回调处理与自动登录

回调地址拿到 code 后，第一步是校验 state 防 CSRF，然后用 code 换 access_token：

```php
public function actionCallback()
{
    $code = Yii::$app->request->get('code');
    $state = Yii::$app->request->get('state');

    // 校验 state
    if ($state !== Yii::$app->session->get('oauth_state')) {
        throw new BadRequestHttpException('Invalid state');
    }

    // 用 code 换 access_token
    $token = $this->getAccessToken($code);
    $openid = $token['openid'];

    // 查找或创建用户
    $user = User::findOne(['openid' => $openid]);
    if (!$user) {
        $user = new User();
        $user->openid = $openid;
        $user->created_at = time();
        $user->save();
    }

    // 自动登录
    Yii::$app->user->login($user, 3600 * 24 * 30);

    return $this->redirect(['site/index']);
}

private function getAccessToken($code)
{
    $appId = Yii::$app->params['wechat']['appId'];
    $appSecret = Yii::$app->params['wechat']['appSecret'];

    $url = "https://api.weixin.qq.com/sns/oauth2/access_token"
         . "?appid={$appId}"
         . "&secret={$appSecret}"
         . "&code={$code}"
         . "&grant_type=authorization_code";

    $result = json_decode(file_get_contents($url), true);
    if (isset($result['errcode'])) {
        throw new Exception('微信授权失败: ' . $result['errmsg']);
    }
    return $result;
}
```

这里有个坑：`file_get_contents` 请求微信接口在某些环境下会超时，建议用 cURL 或者 Guzzle，设置合理的超时时间。我后来换成了 cURL，稳定性好很多。

## 二、会员卡体系设计

会员卡的核心是账户余额，涉及充值和消费两个方向。数据库设计上，我用了两张表：`member_card`（会员卡主表）和 `member_card_log`（余额变动流水表）。

### 2.1 数据库表结构

```sql
CREATE TABLE `member_card` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `user_id` int(11) NOT NULL COMMENT '用户ID',
  `card_no` varchar(32) NOT NULL COMMENT '卡号',
  `balance` decimal(10,2) NOT NULL DEFAULT '0.00' COMMENT '余额',
  `total_recharge` decimal(10,2) NOT NULL DEFAULT '0.00' COMMENT '累计充值',
  `total_consume` decimal(10,2) NOT NULL DEFAULT '0.00' COMMENT '累计消费',
  `status` tinyint(1) NOT NULL DEFAULT '1' COMMENT '状态 1正常 0冻结',
  `created_at` int(11) NOT NULL,
  `updated_at` int(11) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `user_id` (`user_id`),
  UNIQUE KEY `card_no` (`card_no`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `member_card_log` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `card_id` int(11) NOT NULL,
  `type` tinyint(1) NOT NULL COMMENT '类型 1充值 2消费 3退款',
  `amount` decimal(10,2) NOT NULL COMMENT '变动金额',
  `balance_before` decimal(10,2) NOT NULL COMMENT '变动前余额',
  `balance_after` decimal(10,2) NOT NULL COMMENT '变动后余额',
  `order_no` varchar(32) DEFAULT NULL COMMENT '关联订单号',
  `remark` varchar(255) DEFAULT NULL COMMENT '备注',
  `created_at` int(11) NOT NULL,
  PRIMARY KEY (`id`),
  KEY `card_id` (`card_id`),
  KEY `created_at` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

流水表一定要记录变动前后的余额，这是对账的基础。出了问题能追溯到每一笔。

### 2.2 余额变动的事务处理

充值和消费都必须在事务里完成，同时更新余额表和写入流水。这里用了 Yii2 的事务：

```php
public function consume($cardId, $amount, $orderNo, $remark = '')
{
    $transaction = Yii::$app->db->beginTransaction();
    try {
        // 行锁，防止并发消费
        $card = MemberCard::findOne($cardId);
        if (!$card) {
            throw new Exception('会员卡不存在');
        }
        if ($card->balance < $amount) {
            throw new Exception('余额不足');
        }

        $balanceBefore = $card->balance;
        $balanceAfter = $card->balance - $amount;

        // 更新余额
        $card->balance = $balanceAfter;
        $card->total_consume += $amount;
        $card->save();

        // 写入流水
        $log = new MemberCardLog();
        $log->card_id = $cardId;
        $log->type = 2; // 消费
        $log->amount = $amount;
        $log->balance_before = $balanceBefore;
        $log->balance_after = $balanceAfter;
        $log->order_no = $orderNo;
        $log->remark = $remark;
        $log->created_at = time();
        $log->save();

        $transaction->commit();
        return true;
    } catch (Exception $e) {
        $transaction->rollBack();
        throw $e;
    }
}
```

并发场景下，光靠事务还不够，需要用行锁（`SELECT ... FOR UPDATE`）或者乐观锁。Yii2 的 `findOne` 默认不加锁，高并发下可能出现超卖。我后来在消费接口加了 `SELECT ... FOR UPDATE`：

```php
$card = MemberCard::findBySql(
    'SELECT * FROM member_card WHERE id = :id FOR UPDATE',
    [':id' => $cardId]
)->one();
```

## 三、微信支付充值

充值走微信支付 JSAPI，用户在公众号里点击充值，调起微信支付，支付成功后回调更新余额。

### 3.1 统一下单

```php
public function actionRecharge()
{
    $amount = Yii::$app->request->post('amount'); // 单位：元
    $user = Yii::$app->user->identity;

    $orderNo = 'RC' . date('YmdHis') . rand(1000, 9999);

    // 创建充值订单
    $order = new RechargeOrder();
    $order->user_id = $user->id;
    $order->order_no = $orderNo;
    $order->amount = $amount;
    $order->status = 0; // 待支付
    $order->save();

    // 微信统一下单
    $wechatPay = new WechatPay();
    $jsApiParams = $wechatPay->unifiedOrder([
        'body' => '会员卡充值',
        'out_trade_no' => $orderNo,
        'total_fee' => intval($amount * 100), // 分
        'openid' => $user->openid,
        'notify_url' => 'https://your-domain.com/wechat/pay-notify',
    ]);

    return $this->asJson([
        'code' => 0,
        'data' => $jsApiParams,
    ]);
}
```

### 3.2 支付回调

回调是最容易出问题的地方，一定要做好幂等处理。微信可能会多次回调，同一个订单号只能处理一次。

```php
public function actionPayNotify()
{
    $xml = file_get_contents('php://input');
    $data = $this->xmlToArray($xml);

    // 验证签名
    if (!$this->verifySign($data)) {
        return $this->arrayToXml(['return_code' => 'FAIL', 'return_msg' => '签名错误']);
    }

    if ($data['result_code'] != 'SUCCESS') {
        return $this->arrayToXml(['return_code' => 'SUCCESS']);
    }

    $orderNo = $data['out_trade_no'];
    $transactionId = $data['transaction_id'];

    $transaction = Yii::$app->db->beginTransaction();
    try {
        $order = RechargeOrder::findOne(['order_no' => $orderNo]);
        if (!$order || $order->status != 0) {
            // 已处理过，直接返回成功（幂等）
            $transaction->commit();
            return $this->arrayToXml(['return_code' => 'SUCCESS']);
        }

        // 更新订单状态
        $order->status = 1;
        $order->transaction_id = $transactionId;
        $order->paid_at = time();
        $order->save();

        // 充值到会员卡
        $cardService = new MemberCardService();
        $cardService->recharge($order->user_id, $order->amount, $orderNo);

        $transaction->commit();
        return $this->arrayToXml(['return_code' => 'SUCCESS']);
    } catch (Exception $e) {
        $transaction->rollBack();
        Yii::error('支付回调失败: ' . $e->getMessage());
        return $this->arrayToXml(['return_code' => 'FAIL']);
    }
}
```

## 四、踩过的坑

**1. 授权域名配置**

微信公众号后台的"网页授权域名"只能填一个，而且必须是备案域名。开发环境可以用测试号，测试号的授权域名限制少一些。

**2. 支付回调的签名验证**

微信支付回调的 XML 里，`sign` 字段不参与签名计算。验证签名时要把 `sign` 字段去掉，然后按字典序排序拼接密钥。这个细节搞错了会一直验签失败。

**3. 金额单位**

微信支付的金额单位是分，不是元。`total_fee` 必须是整数。一开始我直接传了元，导致支付金额差了100倍，还好是测试环境发现的。

**4. 回调幂等**

微信支付回调不是只调一次，网络抖动或者超时的情况下会重复回调。一定要按订单号做幂等，否则会重复充值。

**5. 并发消费超卖**

上线初期没加行锁，遇到过两次并发请求同时消费，余额变成负数的情况。后来加了 `SELECT ... FOR UPDATE` 行锁才解决。

## 五、总结

这套方案跑了一年多，支撑了上门洗车和社区便利店两个业务线，会员充值消费闭环稳定。核心经验就三条：

1. 授权登录用 `snsapi_base` 静默授权，用户体验最好
2. 余额变动必须在事务里完成，同时记录流水，高并发加行锁
3. 支付回调一定要做幂等和签名验证，这是资金安全的底线

后来项目迭代加了优惠券、积分兑换，都是在这个基础上扩展的。架构上留了扩展空间，加新功能不用动核心表结构。

如果你们也在做类似的微信生态项目，有问题可以交流。
