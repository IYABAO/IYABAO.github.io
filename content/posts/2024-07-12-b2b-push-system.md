---
title: "B 端推送系统设计：多渠道消息防重与异步削峰的工程实践"
date: 2024-07-12T10:00:00+08:00
draft: false
tags: ["消息推送", "B端", "异步处理", "防重", "Go", "RabbitMQ"]
categories: ["架构设计"]
summary: "B 端消息推送系统的架构设计，支持多渠道（站内信、短信、邮件、微信）消息推送，涵盖异步削峰、幂等防重、渠道路由、失败重试，支撑大促期间百万级推送稳定运行。"
keywords: ["消息推送", "防重", "异步削峰", "RabbitMQ", "B端"]
---

B 端企业用户需要接收各种消息通知——简历投递通知、面试邀请、系统公告、活动提醒等，通过站内信、短信、邮件、微信服务号多个渠道推送。2024年7月做了统一的 B 端推送系统，今天把设计实践分享出来。

## 一、架构

```text
业务系统 → 推送 API → 消息队列（RabbitMQ）→ 推送消费者 → 渠道适配器 → 第三方渠道（短信/邮件/微信）
                              ↓
                        消息存储（MySQL）+ 状态追踪（Redis）
```

## 二、核心设计

### 异步削峰

推送请求不直接调用第三方渠道，先发消息队列，消费者异步处理：

```go
func (h *PushHandler) Push(c *gin.Context) {
    var req PushRequest
    c.ShouldBindJSON(&req)

    // 1. 存消息记录
    msg := h.messageRepo.Create(req)

    // 2. 发队列，异步推送
    h.queue.Publish(&PushMessage{MessageID: msg.ID})

    c.JSON(200, gin.H{"code": 0, "message_id": msg.ID})
}
```

### 幂等防重

同一个消息可能被多次消费（队列重投、网络重试），用消息 ID 做幂等：

```go
func (c *PushConsumer) Consume(msg *PushMessage) error {
    // 幂等检查：已推送成功的直接返回
    status := c.redis.Get("push:status:" + msg.MessageID).Val()
    if status == "success" {
        return nil
    }

    // 推送
    err := c.pushToChannel(msg)
    if err != nil {
        return err // 失败，队列重试
    }

    // 标记成功
    c.redis.Set("push:status:"+msg.MessageID, "success", 24*time.Hour)
    c.messageRepo.UpdateStatus(msg.MessageID, "success")
    return nil
}
```

### 渠道路由

根据用户偏好和消息类型选择推送渠道：

```go
func (r *ChannelRouter) Route(userID int64, msgType string) []string {
    // 1. 查用户推送偏好
    preferences := r.userRepo.GetPushPreferences(userID)

    // 2. 根据消息类型选渠道
    var channels []string
    switch msgType {
    case "resume_apply":
        channels = []string{"inapp", "sms", "wechat"} // 重要消息多渠道
    case "system_notice":
        channels = []string{"inapp"} // 系统通知只发站内信
    case "activity":
        channels = []string{"inapp", "email"} // 活动推站内信+邮件
    }

    // 3. 过滤用户关闭的渠道
    return filterChannels(channels, preferences)
}
```

### 失败重试

第三方渠道调用失败，指数退避重试：

```go
func (c *PushConsumer) pushWithRetry(msg *PushMessage) error {
    maxRetries := 3
    for i := 0; i < maxRetries; i++ {
        err := c.pushToChannel(msg)
        if err == nil {
            return nil
        }
        // 指数退避：1s, 2s, 4s
        time.Sleep(time.Second * time.Duration(1<<i))
    }
    // 重试失败，进死信队列
    c.dlq.Publish(msg)
    return errors.New("push failed after retries")
}
```

## 三、限流保护

第三方渠道有调用频率限制，用令牌桶限流：

```go
// 短信渠道每秒最多 100 条
limiter := rate.NewLimiter(rate.Limit(100), 100)
if !limiter.Allow() {
    return errors.New("rate limited")
}
```

## 四、踩坑经验

1. **短信重复发送**：早期没做幂等，队列重投导致用户收到多条短信。加了 Redis 幂等检查后解决
2. **微信模板消息限流**：微信服务号模板消息有频率限制，没做限流导致大量推送失败。加了渠道级别的令牌桶限流
3. **消息堆积**：大促期间推送量暴增，消费者处理不过来队列堆积。加了消费者自动扩容（根据队列长度动态增加消费者数量）
4. **渠道优先级**：同一消息多渠道推送时，应该站内信先发，短信后发（短信要钱）。加了渠道优先级和延迟发送机制

## 五、总结

B 端推送系统核心：

1. **异步化**：推送请求入队，消费者异步处理，接口快速响应
2. **幂等防重**：消息 ID 去重，防止重复推送
3. **渠道路由**：根据消息类型和用户偏好选择推送渠道
4. **失败重试**：指数退避重试 + 死信队列，保证最终送达
5. **限流保护**：每个渠道独立限流，防止触发第三方限制
6. **可观测**：推送成功率、渠道耗时、失败原因都要监控

推送系统的特点是"量大、渠道多、第三方不可控"，核心思路是异步解耦 + 幂等防重 + 失败重试。把不可控的第三方调用封装在消费者里，出问题不影响主业务，重试和死信保证最终一致。
