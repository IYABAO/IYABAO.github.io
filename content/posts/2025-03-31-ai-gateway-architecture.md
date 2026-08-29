---
title: "AI 网关架构设计：One-API 大模型网关的鉴权、限流与计费闭环"
date: 2025-03-31T14:00:00+08:00
draft: false
tags: ["AI", "网关", "One-API", "大模型", "Go", "鉴权", "限流", "计费"]
categories: ["AI架构"]
summary: "基于 One-API 的大模型网关架构设计，涵盖多模型统一接入、API Key 鉴权、限流策略、Token 计费、会员体系，实现 AI 能力的商业化闭环。"
keywords: ["AI网关", "One-API", "鉴权", "限流", "计费"]
---

AI 模拟面试、AI 简历解析、AI 职位生成等功能需要调用多个大模型（GPT、Claude、通义千问、文心一言），如果每个业务单独对接模型 API，维护成本高且无法统一计费。2025年3月基于 One-API 搭建了大模型网关，今天把架构设计分享出来。

## 一、架构

```
业务系统 → AI 网关（One-API）→ 模型供应商（OpenAI/Anthropic/阿里/百度）
                ↓
          鉴权 + 限流 + 计费 + 日志 + 缓存
```

## 二、核心功能

### 多模型统一接入

One-API 支持多种大模型，统一 OpenAI 格式的 API：

```go
// 业务系统调用，不用关心底层是哪个模型
resp, err := http.Post("https://ai-gateway.example.com/v1/chat/completions",
    "application/json",
    bytes.NewBuffer([]byte(`{
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": "你好"}]
    }`)))
```

切换模型只需要改 `model` 参数，业务代码不用改。

### API Key 鉴权

每个业务系统分配独立的 API Key，网关校验 Key 的有效性和权限：

```sql
CREATE TABLE `api_key` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `key` varchar(64) NOT NULL,
  `name` varchar(50) NOT NULL COMMENT 'Key名称（哪个业务用）',
  `user_id` int(11) NOT NULL,
  `allowed_models` text COMMENT '允许使用的模型，逗号分隔',
  `rate_limit` int(11) NOT NULL DEFAULT 60 COMMENT '每分钟请求数限制',
  `token_limit` int(11) DEFAULT NULL COMMENT 'Token总量限制，null不限',
  `token_used` int(11) NOT NULL DEFAULT 0,
  `status` tinyint(1) NOT NULL DEFAULT '1',
  `expired_at` int(11) DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `key` (`key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

### 限流

基于 Redis 的令牌桶限流，每个 Key 独立限流：

```go
func rateLimit(key string, limit int) bool {
    redisKey := "ai:rate:" + key
    count := redis.Incr(redisKey).Val()
    if count == 1 {
        redis.Expire(redisKey, time.Minute)
    }
    return count <= limit
}
```

### Token 计费

每次调用后统计 Token 用量，按模型单价计费：

```go
func recordUsage(key string, model string, promptTokens int, completionTokens int) {
    // 1. 查模型单价
    price := getModelPrice(model) // 元/1K tokens

    // 2. 计算费用
    totalTokens := promptTokens + completionTokens
    cost := float64(totalTokens) / 1000 * price

    // 3. 记录用量
    UsageLog{
        Key: key, Model: model,
        PromptTokens: promptTokens, CompletionTokens: completionTokens,
        Cost: cost, CreatedAt: time.Now(),
    }.Save()

    // 4. 更新 Key 已用 Token
    redis.IncrBy("ai:token_used:"+key, int64(totalTokens))
}
```

### 会员计费闭环

AI 模拟面试是增值服务，会员体系和 AI 网关打通：

```
用户购买会员 → 生成 API Key（绑定会员，Token 限制=会员额度）→ 业务系统用 Key 调用 AI → 扣减 Token → Token 用完提示升级
```

## 三、高可用设计

1. **模型降级**：主模型调用失败时自动切换到备用模型（如 GPT-4o 失败切到通义千问）
2. **超时控制**：每个模型调用设置超时（30秒），超时返回错误不 hang 住
3. **缓存**：相同问题的回答缓存（Redis），减少重复调用，降低成本
4. **异步队列**：非实时需求（如批量简历解析）走异步队列，削峰填谷

## 四、踩坑经验

1. **Token 统计不准**：不同模型的 Token 计算方式不一样，不能用字符数估算。用模型返回的 `usage` 字段统计，最准确
2. **流式响应计费**：SSE 流式响应时，Token 统计要等流结束后统计，不能边流边计（可能不准）
3. **模型价格变动**：模型供应商会调价，价格要配置化，不要硬编码
4. **API Key 泄露**：Key 泄露会导致被盗刷。加 IP 白名单、异常用量告警、Key 轮换机制

## 五、总结

AI 网关架构核心：

1. **统一接入**：多模型统一 OpenAI 格式 API，业务系统不用关心底层模型
2. **鉴权体系**：API Key 鉴权，每个业务独立 Key，权限和限制隔离
3. **限流保护**：令牌桶限流，防止突发流量打垮模型供应商或产生巨额费用
4. **计费闭环**：Token 用量统计 + 模型单价计费 + 会员体系，实现商业化
5. **高可用**：模型降级、超时控制、缓存、异步队列，保证稳定性
6. **可观测**：调用日志、用量统计、异常告警，出问题能快速定位

AI 网关是 AI 能力商业化的基础设施，把模型调用的鉴权、限流、计费、监控都统一处理，业务系统只需要关注业务逻辑。基于 One-API 二次开发，不用从零搭建，能快速落地。
