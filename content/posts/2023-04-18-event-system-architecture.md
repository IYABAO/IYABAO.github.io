---
title: "专场活动系统架构设计：从报名到签到的全链路技术方案"
date: 2023-04-18T14:00:00+08:00
draft: false
tags: ["活动系统", "架构设计", "PHP", "Go", "Redis", "二维码"]
categories: ["架构设计"]
summary: "招聘专场活动系统的全链路架构设计，涵盖活动创建、报名审核、电子票、二维码签到、数据统计，以及高并发报名场景下的性能优化方案。"
---

招聘平台的专场活动（线下招聘会、企业宣讲会、行业沙龙）需要完整的活动管理系统——创建活动、在线报名、审核、电子票、现场签到、数据统计。2023年做了专场活动系统的重构，今天把架构设计分享出来。

## 一、核心流程

```text
创建活动 → 发布上线 → 用户报名 → 审核（自动/人工）→ 发放电子票 → 现场扫码签到 → 数据统计
```

## 二、系统架构

```text
前端（H5/小程序） → API 网关 → 活动服务（Go）
                              ↓
                    报名服务（Go）→ 消息队列 → 通知服务（PHP）
                              ↓
                    签到服务（Go）→ Redis（实时统计）
                              ↓
                    MySQL（业务数据）+ Redis（缓存/限流）+ OSS（票券二维码）
```

核心服务用 Go 写（高并发），通知等非核心服务用 PHP（快速开发）。

## 三、关键功能设计

### 3.1 报名与限流

热门活动报名瞬间流量大，用 Redis 限流 + 原子计数：

```go
func (s *SignupService) Signup(activityId, userId int) error {
    // 1. 幂等检查
    if s.redis.SIsMember(ctx, "signup:users:"+itoa(activityId), userId).Val() {
        return errors.New("已报名")
    }
    
    // 2. 名额检查（原子操作）
    countKey := "signup:count:" + itoa(activityId)
    count := s.redis.Incr(ctx, countKey).Val()
    maxCount := s.getActivityMaxCount(activityId)
    if count > maxCount {
        s.redis.Decr(ctx, countKey)
        return errors.New("名额已满")
    }
    
    // 3. 异步写数据库
    s.queue.Publish(&SignupMessage{ActivityID: activityId, UserID: userId})
    
    // 4. 标记已报名
    s.redis.SAdd(ctx, "signup:users:"+itoa(activityId), userId)
    
    return nil
}
```

### 3.2 电子票与二维码

报名审核通过后生成电子票，用 JWT 编码票信息，二维码存 OSS：

```go
// 生成票 Token
ticket := jwt.NewWithClaims(jwt.SigningMethodHS256, jwt.MapClaims{
    "ticket_id": ticketId,
    "activity_id": activityId,
    "user_id": userId,
    "exp": time.Now().Add(7 * 24 * time.Hour).Unix(),
})
token, _ := ticket.SignedString([]byte(secret))

// 生成二维码
qrCode := qrcode.New(token, qrcode.Medium)
qrFile, _ := qrCode.PNG(256)
oss.Upload("tickets/"+ticketId+".png", qrFile)
```

### 3.3 扫码签到

现场扫码签到，用 Redis 做实时统计和防重复签到：

```go
func (s *CheckinService) Checkin(ticketToken string) (*CheckinResult, error) {
    // 1. 验证票 Token
    claims, err := s.parseTicketToken(ticketToken)
    if err != nil {
        return nil, errors.New("无效票券")
    }
    
    // 2. 防重复签到（Redis SETNX）
    checkinKey := "checkin:" + claims["ticket_id"]
    if !s.redis.SetNX(ctx, checkinKey, "1", 24*time.Hour).Val() {
        return nil, errors.New("已签到")
    }
    
    // 3. 异步写签到记录
    s.queue.Publish(&CheckinMessage{TicketID: claims["ticket_id"]})
    
    // 4. 实时统计+1
    s.redis.Incr(ctx, "checkin:count:"+claims["activity_id"])
    
    return &CheckinResult{Success: true, UserName: claims["user_name"]}, nil
}
```

## 四、性能优化

1. **活动详情页缓存**：Redis 缓存活动信息，5分钟过期
2. **报名异步化**：报名请求先写 Redis，异步写数据库，响应时间 < 50ms
3. **签到本地化**：现场签到服务部署在活动现场附近，减少网络延迟
4. **二维码预生成**：审核通过后立即生成二维码，签到时不用实时生成

## 五、踩坑经验

1. **报名并发超卖**：早期用"先查再写"的方式判断名额，并发下超卖。改成 Redis INCR 原子计数后解决。
2. **二维码过期**：票 Token 过期时间设太短，活动还没开始就过期了。改成活动结束后过期。
3. **签到网络差**：现场网络不稳定，签到超时。加了离线签到模式（本地记录，网络恢复后同步）。

## 六、总结

专场活动系统的核心设计：

1. **异步化**：报名、通知、签到记录都异步处理，核心接口快速响应
2. **原子操作**：名额计数、防重复签到用 Redis 原子操作，防止并发问题
3. **实时统计**：签到数据实时更新，活动方可实时查看到场情况
4. **高可用**：核心服务 Go 开发，非核心 PHP，兼顾性能和开发效率
5. **现场适配**：考虑现场网络差的情况，支持离线签到

活动系统的特点是流量峰值高（报名开始和活动当天），平时流量低。架构设计要考虑峰值场景，用缓存、异步、原子操作扛住高并发，同时保证数据一致性。
