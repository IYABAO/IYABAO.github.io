---
title: "LLM 流式响应的工程化：从代理到协议"
date: 2026-07-07T09:00:00+08:00
lastmod: 2026-07-07T09:00:00+08:00
draft: false
author: IYABAO
tags:
  - SSE
  - LLM
  - Go
categories:
  - 技术
summary: "SSE 不是'把响应流转发'那么简单：心跳、断线重连、背压、取消传播、事件协议。从 Go 代理到客户端渲染，LLM 流式响应的完整工程实践。"
---

# LLM 流式响应的工程化：从代理到协议

流式（Streaming）是 LLM 应用的体验标配——但"把 LLM 的流转发给前端"只是入门。**心跳、断线、取消、背压、事件协议**——每个都是线上事故的高发区。这篇文章是 LLM 流式的完整工程实践（基于自研 SSE 代理引擎）。

## 一、为什么流式难

```
LLM 生成的流（token 序列）
   → 经过：LLM 网关 → 业务服务 → 反向代理 → CDN → 浏览器
   → 每一层都可能：缓冲、超时、断开、乱序

问题：
  1. 中间层缓冲：Nginx 攒够 4KB 才发 → 流式变"等全部"
  2. 长连接断线：30s 无数据被中间层掐断
  3. 客户端断开：服务端还在调 LLM（浪费 token）
  4. 错误无处放：流中间出错，怎么告诉客户端
```

## 二、SSE 协议基础

```
HTTP 响应：Content-Type: text/event-stream
格式：
  data: {"content": "你"}\n\n
  data: {"content": "好"}\n\n
  event: done\n
  data: {}\n\n

关键：
  ✅ 每行以 \n\n 结束（事件分隔）
  ✅ 可以自定义事件类型（done/error/retry）
  ✅ 连接保持（直到服务器结束或断开）
```

## 三、服务端工程要点

### 1. 穿透中间层（不缓冲）

```go
func streamHandler(w http.ResponseWriter, r *http.Request) {
    // 关键头：让中间层不缓冲
    w.Header().Set("Content-Type", "text/event-stream")
    w.Header().Set("Cache-Control", "no-cache")
    w.Header().Set("Connection", "keep-alive")
    w.Header().Set("X-Accel-Buffering", "no")   // Nginx 关缓冲
    flusher, _ := w.(http.Flusher)
    ...
}
```

### 2. 心跳（防中间层超时）

```go
// 每 15s 发一条注释（SSE 注释不渲染，但连接活跃）
ticker := time.NewTicker(15 * time.Second)
go func() {
    for range ticker.C {
        fmt.Fprintf(w, ": ping\n\n")     // 注释行 = 心跳
        flusher.Flush()
    }
}()
```

**注意**：心跳和实际数据要协调（有数据就不发心跳，避免数据+心跳都发导致混乱）。

### 3. 取消传播（客户端断开 → 停 LLM）

```go
// 客户端断开 → r.Context() 取消 → 传给 LLM 调用
ctx := r.Context()
stream, err := llm.Stream(ctx, prompt)   // 带 ctx
// 客户端断开 → ctx 取消 → LLM 停止 → 不再计费
```

**这是最容易被忽略的省钱点**：客户端关了页面，LLM 还在生成 = 白烧 token。

### 4. 背压控制

```go
// LLM 生成快（如 100 token/s），客户端/网络慢
// → 要缓冲 + 限速，否则内存/带宽爆
chunk := <-stream
// 用带缓冲的 channel + 客户端消费速度控制
// 或直接依赖 TCP 背压（HTTP/1.1 下 Flush 会阻塞）
```

**实际**：HTTP/1.1 下 `Flush()` 天然有背压（TCP 缓冲区满会阻塞）。HTTP/2 要额外处理（流独立，不受单连接背压）。

### 5. 事件协议（错误/重试/元数据）

```json
// 数据事件
event: delta
data: {"content": "你", "index": 42}

// 元数据（思考过程/用量）
event: meta
data: {"tokens": 123, "model": "gpt-4o"}

// 错误（可恢复/不可恢复）
event: error
data: {"code": "UPSTREAM_TIMEOUT", "retryable": true}

// 结束
event: done
data: {"usage": {"in": 1200, "out": 350}}
```

**事件协议的价值**：客户端能区分"流结束"和"流中断"、能处理错误重连、能展示思考过程。

## 四、客户端工程要点

### 1. 解析与渲染

```js
const es = new EventSource("/api/chat");   // GET 场景
// 或 fetch + ReadableStream（POST 场景，EventSource 不支持 POST）
const reader = resp.body.getReader();
const decoder = new TextDecoder();
while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    renderDelta(decoder.decode(value));   // 逐块渲染
}
```

**注意**：

```
✅ EventSource 只支持 GET → 带 body 的请求用 fetch 流式
✅ 中文按 UTF-8 解码可能跨 chunk 截断（用 TextDecoder 处理）
✅ 渲染用"追加"不用"重渲染"（性能）
```

### 2. 断线重连

```
客户端策略：
  收到 error(可重试) → 显示"重连中" → 3s 后重试（最多 3 次）
  收到 error(不可重试) → 显示错误 + 已生成内容保留
  连接断开（无事件）→ 心跳超时检测 → 重连
```

**关键**：重连时**携带已收到的 index**（服务端从断点续发，避免重复/缺失）。

### 3. 取消（用户停止生成）

```
用户点"停止" → abort() / controller.abort()
→ 服务端收到 ctx 取消 → 停 LLM → 停计费
```

## 五、压测与监控

```
监控指标：
  连接时长分布（长连接占比）
  心跳超时率（中间层断开比例）
  TTFT P95（首字延迟）
  token/秒（生成速率）
  断线重连率
压测注意：
  长连接占用连接数（单机 65535 限制 → 服务端连接管理）
  内存（大响应缓冲）
```

## 六、踩坑记录

1. **Nginx 缓冲**：`X-Accel-Buffering: no` 漏配 → 流式变"等全部完成"（用户以为卡死）
2. **心跳和 done 冲突**：心跳把 done 顶掉 → 事件序列错乱 → 心跳在独立 goroutine + done 前停止心跳
3. **客户端断开没停 LLM**：token 白烧 → ctx 传播 + 服务端侧超时兜底
4. **中文乱码**：chunk 中间断开 UTF-8 字符 → TextDecoder(stream: true) 处理

## 总结

LLM 流式工程化的核心认知：

1. **穿透中间层**：X-Accel-Buffering、SSE 头、心跳——一个不能少
2. **取消传播**：客户端断开 = 停 LLM = 省钱
3. **事件协议**：delta/meta/error/done，让客户端"懂"流
4. **断线重连**：带断点续传，体验无缝

**流式不是"把流转发"，是"把生成过程变成可靠的实时协议"。** 每层都稳了，用户才觉得"真快、真稳"。
