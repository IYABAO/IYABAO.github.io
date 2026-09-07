---
title: "SSE vs WebSocket：AI 流式场景怎么选"
date: 2025-01-15T09:00:00+08:00
lastmod: 2025-01-15T09:00:00+08:00
draft: false
author: IYABAO
tags:
  - SSE
  - WebSocket
  - AI
  - 流式
categories:
  - 技术
summary: "AI 对话要打字机效果，选 SSE 还是 WebSocket？从协议机制、代理兼容、断线重连、服务端实现四个维度对比，结论：90% 的 AI 场景选 SSE，剩下 10% 才需要 WebSocket。"
---

# SSE vs WebSocket：AI 流式场景怎么选

做 AI 模拟面试，第一个技术选型就是：**LLM 的 token 流式输出，用 SSE 还是 WebSocket？** 我们一开始用 PHP + Socket（WebSocket 的早期方案），后来全换成了 Go 自研 SSE 代理。这篇文章说说为什么。

## 一、先搞清楚两者的本质

| 维度 | SSE（Server-Sent Events） | WebSocket |
|---|---|---|
| 方向 | 单向（服务器 → 客户端） | 双向 |
| 协议 | HTTP（基于普通 GET） | 独立协议（ws://，需握手升级） |
| 数据格式 | 文本（`data: {...}\n\n`） | 任意（文本/二进制帧） |
| 自动重连 | **浏览器原生支持**（EventSource） | 需自己实现 |
| 代理兼容 | 走标准 HTTP，CDN/网关无压力 | 需要代理支持 Upgrade，常被拦 |
| 服务端实现 | 普通 HTTP handler 即可 | 需要协议实现/连接管理 |

**关键洞察**：AI 对话场景 95% 的数据流是**单向**的（LLM → 用户），用户输入是低频的小消息（一轮对话一两句）。拿双向通道跑单向流量，纯属杀鸡用牛刀。

## 二、为什么 AI 场景默认选 SSE

### 1. 代理和网关兼容性是硬优势

我们线上有 Ingress、CDN、WAF。SSE 就是 HTTP 长响应，**所有现成的基础设施都认识它**；WebSocket 要过 Upgrade 握手，任何一层代理不支持就完蛋（我们早期 PHP WebSocket 就在内网代理上卡了很久）。

### 2. 断线重连白送

EventSource 原生自动重连 + `Last-Event-ID` 断点续传。AI 对话中间断网，重连后从断点继续收 token——**WebSocket 这套全要自己写**，断线重连、心跳、消息补偿，全是坑。

### 3. 服务端极简

```go
// Go 里一个 SSE handler 就这么简单
func streamHandler(w http.ResponseWriter, r *http.Request) {
    flusher, _ := w.(http.Flusher)
    w.Header().Set("Content-Type", "text/event-stream")
    w.Header().Set("Cache-Control", "no-cache")
    for token := range llmStream {
        fmt.Fprintf(w, "data: %s\n\n", token)
        flusher.Flush()   // 关键：立刻推给客户端
    }
    fmt.Fprintf(w, "event: done\ndata: {}\n\n")
}
```

WebSocket 在 Go 里要引 gorilla/websocket、管理连接池、处理 ping/pong——复杂度不是一个量级。

## 三、什么时候才需要 WebSocket

**双向高频实时**的场景，比如：

- 实时协作（多人同时编辑同一份文档）
- 在线游戏（双向高频状态同步）
- 实时客服聊天（双方向高频互发）

**AI 场景里的例外**：如果你的产品有"客户端中断生成 + 服务器停止"的强交互（比如用户可以随时打断 LLM 继续回答），WebSocket 的双向优势会放大——但就算这样，SSE + 单独一个控制请求（`POST /cancel`）也能做到，代价很小。

## 四、SSE 的坑（我们踩过的）

### 坑 1：代理缓冲

Ingress/CDN 默认会缓冲响应，导致 token 到客户端是一坨一坨的，打字机效果没了。

```yaml
# Nginx 配置
proxy_buffering off;
proxy_cache off;
# 或加响应头
X-Accel-Buffering: no
```

**Go 服务端主动加 `X-Accel-Buffering: no` 头**，让中间代理别缓冲。

### 坑 2：超时断连

长连接容易撞各种超时（网关 60s、LB idle timeout）。方案：

- 客户端每 15s 发心跳注释行（SSE 的 `: ping\n\n` 注释不会触发数据事件，但保持连接活跃）
- 服务端配置合理超时（我们设 5 分钟无 token 才断）

### 坑 3：网络错误是常态，客户端要优雅降级

SSE 断了自动重连，但要**提示用户"正在重新连接"**，并在重连成功前标记「已收到的内容」，避免用户以为内容丢了。

### 坑 4：流式 + 计费的边界

AI 商业化必须按 token 计费。流式响应结束（`event: done`）时**服务端要落一次计费记录**，客户端展示"本次消费 X tokens"——别等对话结束才计费，断线场景会漏。

## 五、我们的最终架构

```
用户 ←── SSE（token 流）── Go SSE 代理
  │                          │
  └── POST /chat（发起对话）──┘──► LLM 上游（OpenAI/自研，流式）

Go 代理职责：
  1. 并发管理（每个用户一个 goroutine）
  2. 鉴权 + 计费中间件
  3. Prompt 组装（System/User/Prefill）
  4. 流式透传 + 心跳
```

## 总结

选型一句话：

> **AI 对话场景：默认 SSE。** 数据单向、要过代理、要自动重连——SSE 全对。只有"双向高频"是硬需求时才考虑 WebSocket。

我们弃掉 PHP + Socket 换 Go SSE 后，TTFT（首字延迟）从 800ms 降到 500ms 以内，基础设施问题清零。**选对协议，一半的线上故障就消失了。**
