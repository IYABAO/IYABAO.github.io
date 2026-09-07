---
title: "分布式链路追踪：从日志拼查到 Trace 一键"
date: 2022-08-16T09:00:00+08:00
lastmod: 2022-08-16T09:00:00+08:00
draft: false
author: IYABAO
tags:
  - 链路追踪
  - 可观测
  - 微服务
categories:
  - 技术
summary: "微服务排查的痛：一个请求经过 8 个服务，日志散在 8 个文件里。Trace ID 贯穿、Span 采集、采样策略——从'拼日志'到'一键看全链路'的落地。"
---

# 分布式链路追踪：从日志拼查到 Trace 一键

单体时代排查：一个请求，一个日志文件，顺序看下来就行。微服务时代：一个请求经过 8 个服务，日志散在 8 个地方，**"拼日志"是每个排查人的噩梦**。链路追踪（Distributed Tracing）就是解决这个问题的。

## 一、痛点

```
用户说"下单失败了" → 排查开始：
  查 API 网关日志 → 找到请求
  → 记下 order_id → 查订单服务日志
  → 发现它调了支付服务 → 查支付服务日志
  → 支付服务又调了优惠券服务...
  手工翻 6 个服务 × 各自的时间线 = 半小时起步

痛点：
  1. 跨服务无法串联（每个服务只知道自己的局部）
  2. 耗时不知道在哪（网关 800ms，哪一段慢？）
  3. 异常链路无法还原（出错的完整调用路径）
```

## 二、核心概念

### Trace 与 Span

```
Trace：一次请求的完整链路（一整棵树）
Span：链路中的一个环节（一个服务的一次调用）

下单请求的 Trace：
┌─ api-gateway (span: 下单入口) ──────────────┐
│  ├─ order-service (span: 创建订单) ──────── │
│  │   ├─ payment-service (span: 发起支付) ── │
│  │   └─ coupon-service (span: 核销优惠券)   │
└────────────────────────────────────────────┘
```

### 三个 ID

```
trace_id：整条链路唯一（请求入口生成，全链路传递）
span_id：当前环节唯一（每层生成）
parent_span_id：父环节（构成树结构）
```

## 三、实现：上下文传递

**关键**：trace_id 必须在服务间传递（HTTP header / gRPC metadata / MQ 消息头）。

```go
// 入口：生成 trace_id
func Middleware() gin.HandlerFunc {
    return func(c *gin.Context) {
        traceID := c.GetHeader("X-Trace-Id")
        if traceID == "" {
            traceID = uuid.New()          // 入口生成
        }
        c.Set("trace_id", traceID)
        // 下发给下游
        c.Header("X-Trace-Id", traceID)
        c.Next()
    }
}

// 下游：从 header 取（没有就新生成——链路断了要告警）
traceID := c.GetHeader("X-Trace-Id")
```

**gRPC 传递**：

```go
// 用 metadata 传递
md := metadata.Pairs("x-trace-id", traceID)
ctx = metadata.NewOutgoingContext(ctx, md)
// 服务端
if md, ok := metadata.FromIncomingContext(ctx); ok {
    traceID = md.Get("x-trace-id")[0]
}
```

**MQ 传递**：消息头带 trace_id（RabbitMQ headers / Kafka headers）。

## 四、采集与存储

### 采样策略（成本控制）

```
✅ 全量采样：错误链路（ERROR/异常）
✅ 比例采样：正常请求（10%——统计够了）
✅ 关键接口全量：核心链路（支付/下单）

为什么不全量：每条 Span 有 20+ 字段，
  全量 = 存储爆炸 + 写入压力
  10% 采样 + 错误全采，能覆盖 99% 排查场景
```

### 存储选型

```
Jaeger：开源，ES/Cassandra 后端，部署简单
Zipkin：老牌，轻量
SkyWalking：Java 生态强
自建轻量：ClickHouse 存 Span（量大检索快）
```

## 五、落地效果

```
排查从"半小时拼日志" → "30 秒看全链路"

具体收益：
  1. 慢请求定位：Trace 瀑布图看哪段耗时（一眼看到支付 600ms）
  2. 异常还原：出错请求的完整调用链（哪个服务、什么参数）
  3. 依赖分析：服务调用关系图（谁依赖谁、谁最慢）
  4. 容量规划：各服务实际 QPS/耗时统计
```

## 六、踩坑记录

1. **链路断裂**：下游没接 header → trace_id 丢失 → 入口生成了，下游自己建新 ID → 所有服务必须统一 SDK 传递
2. **异步链路丢失**：goroutine 里没传 context → 异步任务不在链路上 → 协程创建时带上 trace context
3. **采样把错误丢了**：只采样 10%，错误请求恰好没采到 → **错误必须全量采集**
4. **Span 字段太多**：采集 30 个字段 → 存储翻倍 → 只留关键字段（service/操作/耗时/状态/错误）

## 七、与日志/指标的配合

```
三层可观测：
  Metrics（指标）：服务健康（QPS/延迟/错误率）——宏观
  Logs（日志）：细节排查（具体报错/参数）——微观
  Traces（链路）：全链路串联（请求路径/耗时分布）——中观

配合方式：
  告警从指标触发（错误率 > 5%）
  → 定位用 Trace（哪条链路出错）
  → 细节看 Logs（具体错误信息）
```

## 总结

链路追踪的核心认知：

1. **Trace = 一次请求的完整树**：trace_id 贯穿 + span 记录每个环节
2. **上下文传递是地基**：HTTP/gRPC/MQ 全链路传 trace_id，断了就是白做
3. **采样要有策略**：正常 10% + 错误全采 + 核心接口全量
4. **三层配合**：指标触发告警、链路定位、日志看细节

**微服务排查的分水岭：会不会用 Trace。** 有了全链路视图，"这个请求到底经历了什么"就不再是拼出来的，是看出来的。
