---
title: "MCP 生态全景：从 Server 到 Client 到 Hub"
date: 2025-03-04T09:00:00+08:00
lastmod: 2025-03-04T09:00:00+08:00
draft: false
author: IYABAO
tags:
  - MCP
  - AI生态
categories:
  - 技术
summary: "MCP 正在成为 AI 应用的 USB-C 接口。协议分层、Server/Client/Host 三方角色、注册表与 Hub、主流实现对比——MCP 生态的一次全景扫描。"
---

# MCP 生态全景：从 Server 到 Client 到 Hub

MCP（Model Context Protocol）正在成为 AI 应用连接外部世界的"USB-C 接口"：一个协议，让 LLM 统一调用各种工具、读取各种数据源。这篇文章是 MCP 生态的全景扫描：协议、角色、生态、选型。

## 一、MCP 解决什么问题

```
没有 MCP：
  每个 AI 应用 × 每个数据源 = N×M 种定制集成
  Claude 连数据库要写插件，Cursor 连数据库要再写一份

有 MCP：
  数据源作者写一个 MCP Server → 所有 MCP Client 都能用
  一次实现，处处可用（标准 USB 接口）
```

**核心价值**：**解耦**。工具/数据源的能力提供方（Server）和能力消费方（Client/Host）通过标准协议对接，互不感知对方实现。

## 二、协议分层

```
┌─ Host（宿主应用：Claude Desktop / Cursor / 自研 Agent）
│   ├─ Client（MCP 客户端：管理连接、协议交互）
│   └─ Client
└─ Server（MCP 服务端：暴露工具/资源/提示）
```

### 三种能力原语

| 原语 | 作用 | 例子 |
|---|---|---|
| **Tools** | 可调用函数（LLM 决定调用） | 搜简历、发消息、查天气 |
| **Resources** | 可读取数据（应用/用户决定） | 数据库 schema、文档、配置 |
| **Prompts** | 可复用提示模板 | 面试开场、代码审查模板 |

**理解**：Tools 是"操作"，Resources 是"数据"，Prompts 是"模板"——三者的边界很清晰，但初学容易混。**Tools 是 MCP 的核心**，绝大部分场景只用它。

### 传输层

```
stdio：本地进程（标准输入输出），开发/本地工具主流
SSE：HTTP 流式，远程服务
Streamable HTTP：新版推荐（取代纯 SSE）
```

**选型**：本地工具用 stdio（零配置），远程服务用 Streamable HTTP（过代理友好）。

## 三、生态版图

### Server 侧（能力提供）

```
官方/知名 Server：
  GitHub、Slack、Google Drive、Notion、数据库（Postgres/MySQL）
自建 Server（我们做的最多）：
  FastMCP（Python）/ @modelcontextprotocol/sdk（TS）/ go-mcp
```

### Client 侧（能力消费）

```
主流 Host：Claude Desktop、Cursor、VS Code、自研 Agent
MCP 之于 AI 应用 ≈ 插件系统之于浏览器
```

### 注册表与 Hub

```
官方注册表：modelcontextprotocol/servers（官方维护的精选列表）
社区 Hub：smithery.ai、mcp.so（搜索、安装、发现）
```

**注意**：第三方 Hub 的 Server 质量参差，**生产使用前必须审查代码**（它拥有你的数据和工具调用权）。

## 四、主流实现对比

| SDK | 语言 | 成熟度 | 特点 |
|---|---|---|---|
| FastMCP | Python | 高 | 最流行，装饰器极简，中间件 |
| 官方 SDK | TS/Python | 高 | 官方，底层控制强 |
| mcp-go | Go | 中 | Go 生态，适合 Go 服务嵌入 |
| 社区 SDK | Rust/Java 等 | 中低 | 按需 |

**我们选 FastMCP 的原因**：Python 生态（LLM 工具周边最全）、装饰器一行注册、中间件支持鉴权——**企业级落地最快**。

## 五、Server 设计模式（生产经验）

### 模式 1：薄封装（Tool = API 代理）

```
MCP Tool → 内部 HTTP API → 业务系统
```

**适用**：已有系统，快速暴露能力。

### 模式 2：领域服务（Tool = 业务能力）

```
MCP Tool（搜简历）→ 业务服务（ES 检索 + 权限过滤 + 结果裁剪）
```

**适用**：核心资产，要加鉴权、审计、限流。

### 模式 3：资源型（Resources = 数据目录）

```
Resources：数据库表清单、文档库索引（给 LLM 导航用）
Tools：基于资源的具体操作
```

**我们的最佳东方实践**：简历检索走 Tools（带鉴权中间件），人才画像维度走 Resources（只读数据）。

## 六、生产落地的五件事

```
✅ 鉴权：Tool 层必须验 token（LLM 调用不等于无权限）
✅ 审计：所有 Tool 调用记日志（谁、调了什么、结果）
✅ 限流：按调用方/按工具限流（防刷爆上游）
✅ 错误结构：业务错误转 MCP 错误码（LLM 才能理解重试/换方式）
✅ 评测：工具描述写清楚（LLM 选工具靠 description）
```

## 七、MCP 的未来（2025-2026 观察）

- **Agentic MCP**：Server 之间互相调用（MCP 从"工具层"进化到"服务层"）
- **安全标准**：OAuth、权限粒度、审计规范在标准化中
- **MCP 与 RAG 融合**：Tools 即知识入口（查询即检索），替代部分 RAG 管道

## 总结

MCP 生态的核心认知：

1. **一个协议解耦 AI 与数据**：Server 一次实现，Client 处处可用
2. **三方角色**：Host（宿主）/ Client（客户端）/ Server（服务端）
3. **三种原语**：Tools（操作）/ Resources（数据）/ Prompts（模板）
4. **生产五件事**：鉴权、审计、限流、错误、评测

**MCP 是 AI 应用的"接口革命"**——就像 USB-C 统一了外设，MCP 正在统一 AI 的能力接入。现在开始积累 MCP Server 的实践经验，是站在下一个十年的入口。
