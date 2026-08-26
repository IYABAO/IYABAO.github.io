---
title: "消息队列开发现状与问题分析：RabbitMQ 在招聘场景下的踩坑实录"
date: 2023-02-20T10:00:00+08:00
draft: false
tags: ["消息队列", "RabbitMQ", "PHP", "异步处理", "踩坑"]
categories: ["中间件"]
summary: "RabbitMQ 在招聘业务场景下的踩坑实录，涵盖消息丢失、重复消费、队列堆积、死信处理等问题的分析与解决方案，以及消息队列使用的最佳实践。"
---

招聘平台大量使用 RabbitMQ 做异步处理——发邮件、发短信、统计埋点、视频转码、简历解析等等。用了几年，踩了不少坑。今天把消息队列在招聘场景下的问题和解决方案整理出来。

## 一、消息丢失

### 问题

最早用 RabbitMQ 时，消息生产者发完就不管了，消费者处理失败也不重试。有次 RabbitMQ 节点重启，一批报名通知消息丢了，用户没收到报名成功短信，投诉了好几个。

### 解决方案

1. **生产者确认**：开启 publisher confirm，消息到达 Broker 后确认，失败重试
2. **持久化**：队列和消息都设为持久化（durable），重启不丢
3. **消费者手动 ack**：处理成功再 ack，失败不 ack 重新入队
4. **死信队列**：处理失败多次的消息进死信队列，人工排查

```php
// 生产者确认
$channel->confirm_select();
$channel->set_ack_handler(function ($message) {
    // 消息已到达 Broker
});
$channel->set_nack_handler(function ($message) {
    // 消息未到达，重试
});

// 持久化消息
$msg = new AMQPMessage($body, ['delivery_mode' => AMQPMessage::DELIVERY_MODE_PERSISTENT]);
```

## 二、重复消费

### 问题

消费者处理成功但 ack 时网络断了，消息重新入队，消费者又处理一次。报名通知发了两条，用户投诉骚扰。

### 解决方案

**幂等设计**：消费端做幂等，同一个消息处理多次结果一样。

```php
public function handleSignupNotify($message)
{
    $data = json_decode($message->body, true);
    $msgId = $data['message_id'];
    
    // 幂等检查：已处理过直接返回
    if (Yii::$app->redis->sismember("msg:processed:signup", $msgId)) {
        $message->ack();
        return;
    }
    
    // 业务处理
    $this->sendSignupEmail($data['user_id']);
    
    // 标记已处理
    Yii::$app->redis->sadd("msg:processed:signup", $msgId);
    Yii::$app->redis->expire("msg:processed:signup", 86400 * 7);
    
    $message->ack();
}
```

## 三、队列堆积

### 问题

视频转码队列，大促期间上传视频多，转码服务处理不过来，队列堆积几万条，用户等很久视频才转好。

### 解决方案

1. **消费者扩容**：根据队列长度自动扩容消费者实例
2. **优先级队列**：重要消息（如报名通知）优先级高，优先处理
3. **分流**：不同类型消息用不同队列，互不影响
4. **降级**：非核心消息（如统计埋点）堆积时可以丢弃一部分

```php
// 优先级队列
$channel->queue_declare('video_transcode', false, true, false, false, false, [
    'x-max-priority' => ['I', 10],
]);

// 高优先级消息
$msg = new AMQPMessage($body, [
    'delivery_mode' => 2,
    'priority' => 10, // 高优先级
]);
```

## 四、死信处理

### 问题

消费失败的消息不断重试，永远处理失败（如数据格式错误），占用队列资源。

### 解决方案

**死信队列 + 重试次数限制**：

```php
// 声明死信队列
$channel->queue_declare('dlq', false, true, false, false);

// 业务队列绑定死信
$channel->queue_declare('signup_notify', false, true, false, false, false, [
    'x-dead-letter-exchange' => ['S', ''],
    'x-dead-letter-routing-key' => ['S', 'dlq'],
]);

// 消费时判断重试次数
$retryCount = $message->get('application_headers')['x-retry-count'] ?? 0;
if ($retryCount > 3) {
    // 超过3次，直接进死信
    $message->nack(false);
    return;
}

// 处理失败，重试次数+1，重新入队
$message->get('application_headers')->set('x-retry-count', 'I', $retryCount + 1);
$message->nack(true);
```

## 五、顺序消息

### 问题

简历状态变更消息（创建→审核→发布）需要保证顺序，否则状态错乱。RabbitMQ 默认不保证顺序。

### 解决方案

**单队列 + 单消费者**：需要顺序的消息放同一个队列，用单消费者处理（或按 key 哈希到固定消费者）。

```php
// 按 resume_id 哈希，同一个简历的消息到同一个队列
$queueIndex = crc32($resumeId) % $consumerCount;
$channel->basic_publish($msg, '', "resume_status_{$queueIndex}");
```

## 六、总结

RabbitMQ 使用的核心经验：

1. **不丢消息**：生产者确认 + 持久化 + 手动 ack + 死信队列
2. **不重复消费**：消费端幂等设计，消息 ID 去重
3. **不堆积**：消费者扩容 + 优先级队列 + 分流 + 降级
4. **死信处理**：重试次数限制 + 死信队列 + 人工排查
5. **顺序消息**：单队列单消费者，或按 key 哈希固定消费者
6. **监控告警**：队列长度、消费速率、错误率、死信数量，都要监控

消息队列不是"发了就完事"，要考虑消息丢失、重复、堆积、死信等各种异常情况。生产环境用消息队列，一定要做好幂等、重试、监控，否则出了问题排查起来很痛苦。
