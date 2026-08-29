---
title: "MCP 协议深度解析：Tools/Resources/Prompts 三大核心设计"
date: 2025-05-12T14:00:00+08:00
draft: false
tags: ["MCP", "Model Context Protocol", "AI", "大模型", "协议设计", "Anthropic"]
categories: ["AI架构"]
summary: "MCP（Model Context Protocol）协议的深度解析，从设计哲学到三大核心能力 Tools/Resources/Prompts，传输层、安全模型、生命周期管理，以及和 Function Calling、OpenAPI 的本质区别。"
faq:
  - question: "MCP 协议的三大核心设计是什么？"
    answer: "MCP 协议围绕 Tools（工具）、Resources（资源）、Prompts（提示词模板）三大核心设计：Tools 让大模型可以调用外部函数；Resources 让大模型可以读取结构化数据/文件；Prompts 提供可复用的提示词模板，三者配合实现大模型与外部系统的标准化连接。"
  - question: "MCP 相比 Function Calling 有什么优势？"
    answer: "Function Calling 是各家厂商各自定义的私有协议，迁移成本高；MCP 是开放的标准化协议，Claude、Cursor、ChatGPT、Windsurf 等主流产品都原生支持，一套服务可被多个 Agent 复用，生态更广、维护成本更低。"
  - question: "MCP 传输层是怎么工作的？"
    answer: "MCP 采用客户端-服务器模型，通过 JSON-RPC 2.0 进行消息传递，支持 stdio（本地进程通信）和 HTTP/SSE（远程通信）两种传输方式，并支持流式请求和双向通信，适合 Agent 与工具之间的实时交互。"
keywords: ["MCP协议", "Model Context Protocol", "FastMCP", "大模型工具调用", "AI Agent"]
---

MCP（Model Context Protocol）是 Anthropic 在 2024 年底推出的开放协议，目标是让大模型能标准化地连接外部工具和数据。2025年 MCP 生态爆发，Claude、Cursor、Windsurf、ChatGPT 都支持了 MCP。我们在招聘平台做了企业级 MCP 服务，深入研究了协议设计。今天从协议层面做深度解析。

## 一、MCP 解决了什么问题

大模型连接外部能力，之前有几种方式：

1. **Function Calling**：OpenAI 推出的，每个应用自己定义工具 schema，模型调用后应用执行。问题：每个应用都要自己实现一套，工具不能复用，没有标准
2. **插件系统**：ChatGPT Plugins、Claude Tools，各自封闭，不互通
3. **API 集成**：应用自己调第三方 API，模型不直接参与

这些方式的共同问题：**没有统一标准，工具和模型之间是紧耦合的**。你为 Claude 写的工具，不能直接给 Cursor 用；每个 AI 应用都要重新对接一遍工具。

MCP 的核心目标就是**解耦**——把工具和数据封装成标准的 MCP Server，任何支持 MCP 的 Client（Claude、Cursor、ChatGPT 等）都能直接用，不用重复开发。

```text
MCP 之前：
  Claude → 自定义工具A
  Cursor → 自定义工具B（和A功能一样但要重写）
  ChatGPT → 自定义工具C（又要重写）

MCP 之后：
  MCP Server（工具实现一次）
    ├── Claude（MCP Client）直接用
    ├── Cursor（MCP Client）直接用
    ├── ChatGPT（MCP Client）直接用
    └── 任何支持 MCP 的 Client 都能用
```

## 二、设计哲学

MCP 的设计有几个关键原则：

1. **以模型为中心**：协议设计围绕大模型的能力（调用工具、读取资源、使用提示词），不是以人为中心
2. **渐进式能力**：Server 可以只实现部分能力（只实现 Tools 不实现 Resources），Client 按需使用
3. **传输无关**：协议本身不绑定传输层，可以用 stdio、HTTP/SSE、WebSocket
4. **安全第一**：所有操作需要用户确认，Server 不能主动推送，Client 完全控制
5. **JSON-RPC 2.0**：基于成熟的 JSON-RPC 2.0 协议，不用重新发明轮子

## 三、三大核心能力

MCP 定义了三大核心能力：Tools、Resources、Prompts。

### 1. Tools（工具）

Tools 是模型可以**调用**的操作，有输入有输出，会产生副作用（如查询数据库、发送邮件、执行代码）。

**定义**：

```json
{
  "name": "search_resumes",
  "description": "搜索简历，按关键词、城市、工作经验筛选。返回匹配的简历列表。",
  "inputSchema": {
    "type": "object",
    "properties": {
      "keyword": {
        "type": "string",
        "description": "搜索关键词，如'Go开发''前端工程师'"
      },
      "city_id": {
        "type": "integer",
        "description": "城市ID，杭州=2，上海=1，北京=3"
      },
      "experience_min": {
        "type": "integer",
        "description": "最低工作年限",
        "default": 0
      },
      "page": {
        "type": "integer",
        "description": "页码，从1开始",
        "default": 1
      },
      "page_size": {
        "type": "integer",
        "description": "每页数量，最大50",
        "default": 20
      }
    },
    "required": ["keyword"]
  }
}
```

**调用流程**：

```text
1. Client 发送 tools/list → Server 返回所有工具定义
2. 模型根据用户问题选择工具和参数
3. Client 发送 tools/call {name, arguments} → Server 执行工具
4. Server 返回执行结果（文本或结构化数据）
5. 模型根据结果继续回答用户
```

**关键点**：
- `description` 非常重要，模型靠这个理解工具用途，要写清楚功能、参数含义、使用场景
- `inputSchema` 是 JSON Schema，模型按这个生成参数
- 工具调用是同步的，Client 等待 Server 返回结果
- 工具可以返回 `isError: true` 表示执行失败，模型会根据错误信息调整

### 2. Resources（资源）

Resources 是模型可以**读取**的数据，没有副作用，类似"文件"或"API 端点"。模型可以读取资源内容作为上下文。

**定义**：

```json
{
  "uri": "resume://1001",
  "name": "张三的简历",
  "description": "求职者张三的完整简历，包含基本信息、工作经历、教育背景、技能",
  "mimeType": "application/json"
}
```

**读取流程**：

```text
1. Client 发送 resources/list → Server 返回所有资源
2. 模型需要某个资源时，Client 发送 resources/read {uri}
3. Server 返回资源内容
```

**资源模板**：

资源可以是模板化的，支持参数：

```json
{
  "uriTemplate": "resume://{id}",
  "name": "简历详情",
  "description": "根据简历ID获取简历详情",
  "mimeType": "application/json"
}
```

模型可以构造 `resume://1001` 这样的 URI 读取任意简历。

**Resources 和 Tools 的区别**：

| 维度 | Tools | Resources |
|------|-------|-----------|
| 操作 | 调用（有副作用） | 读取（无副作用） |
| 输入 | JSON Schema 参数 | URI（可模板化） |
| 输出 | 执行结果 | 资源内容 |
| 模型行为 | 主动调用 | 读取作为上下文 |
| 类比 | API 端点 | 文件/数据库记录 |

简单说：**Tools 是"做某事"，Resources 是"读某物"**。

### 3. Prompts（提示词）

Prompts 是预定义的提示词模板，模型可以使用，类似"快捷指令"或"工作流模板"。

**定义**：

```json
{
  "name": "resume_optimization",
  "description": "简历优化助手，根据目标岗位优化简历内容",
  "arguments": [
    {
      "name": "resume_content",
      "description": "原始简历内容",
      "required": true
    },
    {
      "name": "target_position",
      "description": "目标岗位，如'Go后端架构师'",
      "required": true
    }
  ]
}
```

**使用流程**：

```text
1. Client 发送 prompts/list → Server 返回所有提示词
2. 用户或模型选择某个提示词，填入参数
3. Client 发送 prompts/get {name, arguments} → Server 返回完整提示词
4. 模型用这个提示词生成回答
```

Prompts 的价值是**把最佳实践固化下来**——比如简历优化、面试评估、JD 生成，这些有固定流程的任务，做成 Prompt 模板，用户一键使用，不用每次重新描述需求。

## 四、传输层

MCP 支持两种传输方式：

### 1. stdio（标准输入输出）

本地进程间通信，适合桌面端 AI 工具（Claude Desktop、Cursor 本地插件）。

```text
Client 进程 ←── stdin/stdout ──→ Server 进程
```

特点：
- 简单，不需要网络
- 本地运行，数据不出本机
- 适合本地工具（文件系统、代码编辑器、本地数据库）
- 每次启动一个 Server 进程

### 2. HTTP/SSE（网络传输）

适合远程 MCP Server，Client 通过 HTTP 连接。

```text
Client ←── HTTP + SSE ──→ MCP Server（远程部署）
```

- 初始化：Client 发 POST 请求建立连接
- 服务端推送：Server 通过 SSE（Server-Sent Events）推送通知
- 客户端请求：Client 发 POST 请求调用方法

特点：
- 可以远程部署，多用户共享
- 适合企业级服务（内部 API、数据库、云服务）
- 需要鉴权和安全控制
- 可以水平扩展

## 五、协议消息格式

MCP 基于 JSON-RPC 2.0，消息格式：

**请求**：

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "search_resumes",
    "arguments": {
      "keyword": "Go开发",
      "city_id": 2
    }
  }
}
```

**响应**：

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "content": [
      {
        "type": "text",
        "text": "找到3份匹配的简历：\n1. 张三 - Go高级工程师 - 5年经验\n2. 李四 - Go架构师 - 8年经验\n3. 王五 - 全栈工程师 - 3年Go经验"
      }
    ],
    "isError": false
  }
}
```

**通知（不需要响应）**：

```json
{
  "jsonrpc": "2.0",
  "method": "notifications/tools/list_changed",
  "params": {}
}
```

## 六、生命周期

MCP 会话的生命周期：

```text
1. 初始化（initialize）
   Client → Server：协议版本、客户端能力
   Server → Client：协议版本、服务端能力、工具/资源/提示词列表

2. 能力协商
   双方确认支持的能力（Tools/Resources/Prompts、日志、进度等）

3. 正常使用
   - tools/list、tools/call
   - resources/list、resources/read
   - prompts/list、prompts/get

4. 通知
   Server 可以推送通知（如工具列表变更、资源更新）

5. 关闭
   Client 发送 shutdown，Server 清理资源
```

## 七、安全模型

MCP 的安全设计很关键，因为工具能操作真实数据：

1. **用户确认**：工具调用前，Client 必须让用户确认（特别是有副作用的操作）。Claude Desktop 会弹窗显示工具名和参数，用户点确认才执行
2. **最小权限**：MCP Server 应该只暴露必要的工具，不要把所有 API 都暴露。比如招聘平台 MCP 只暴露搜索和查看，不暴露删除和修改
3. **鉴权**：HTTP/SSE 传输必须鉴权（API Key、OAuth、JWT），不是谁都能连
4. **数据隔离**：多租户场景下，每个用户只能访问自己权限范围内的数据
5. **审计日志**：所有工具调用记录日志，谁、什么时候、调用了什么工具、参数是什么，可追溯
6. **沙箱执行**：有风险的操作（如执行代码、修改数据）在沙箱里执行，限制权限

## 八、MCP vs Function Calling vs OpenAPI

很多人会混淆这三者，它们有本质区别：

| 维度 | MCP | Function Calling | OpenAPI |
|------|-----|-------------------|---------|
| 定位 | 模型连接外部世界的标准协议 | 单个模型的工具调用能力 | REST API 的描述规范 |
| 范围 | Tools + Resources + Prompts | 只有 Tools（函数调用） | 只有 API 描述 |
| 传输 | stdio / HTTP+SSE | 模型内置（HTTP 请求里） | HTTP |
| 可复用性 | 一次实现，所有 MCP Client 可用 | 每个模型/应用单独实现 | 一次描述，可生成客户端 |
| 发现机制 | 动态 list（运行时获取） | 静态定义（请求时传入） | 静态文件（yaml/json） |
| 安全 | 内置用户确认、鉴权 | 应用自己实现 | 自己实现 |
| 适用场景 | AI 应用连接工具和数据 | 单个大模型应用的工具调用 | REST API 的文档和客户端生成 |

**MCP 和 Function Calling 的关系**：MCP 是更高层的协议，它定义了工具的标准描述和传输方式；Function Calling 是模型调用工具的具体机制。MCP Server 的工具可以通过 Function Calling 被模型调用，也可以通过其他方式。

**MCP 和 OpenAPI 的关系**：OpenAPI 描述 REST API，MCP 描述模型可用的工具/资源/提示词。可以把 OpenAPI 描述的 API 包装成 MCP Server，但 MCP 不止是 API 包装，还有 Resources 和 Prompts。

## 九、MCP 生态

2025年 MCP 生态发展很快：

**Client 端**：
- Claude Desktop / Claude API
- Cursor / Windsurf
- ChatGPT（官方支持）
- Gemini
- Cline / Roo Code（开源）
- 各种 AI IDE 插件

**Server 端**：
- 官方：Filesystem、GitHub、Slack、Google Drive、Notion
- 社区：数据库（PostgreSQL/MySQL）、浏览器（Playwright）、代码搜索、Jira、Linear、Figma
- 企业自建：内部系统、业务 API

**开发框架**：
- Python：FastMCP（推荐，类似 FastAPI）、mcp（官方 SDK）
- TypeScript：@modelcontextprotocol/sdk（官方）
- Go：mcp-go（社区）
- Java：mcp-java（社区）

## 十、踩坑经验

1. **Tool description 写不好模型不会用**：这是最常见的问题。description 要包含：功能是什么、什么时候用、参数含义、使用示例。模型完全靠 description 理解工具
2. **参数默认值很重要**：有默认值的参数模型可以不填，减少模型负担。常用参数（如 page、page_size）一定要给默认值
3. **返回结果不要太长**：工具返回的内容会进入模型上下文，太长会占用 token 且可能干扰模型。返回结果要精简，只返回必要信息，大结果分页
4. **错误信息要友好**：工具执行失败时，返回的错误信息要告诉模型"为什么失败、怎么重试"，模型会根据错误信息调整参数重试。不要只返回"error"
5. **Resources 适合只读数据**：不要把有副作用的操作做成 Resource，Resource 应该是纯读取。有副作用的用 Tools
6. **stdio 适合本地，HTTP 适合服务端**：不要用 stdio 部署远程服务，stdio 是本地进程通信，没有网络能力。远程服务用 HTTP/SSE
7. **幂等性**：工具调用可能重试（网络超时、模型重试），有副作用的工具要保证幂等，用唯一请求 ID 防重
8. **不要暴露敏感操作**：删除、修改、发送等敏感操作，要么不暴露，要么加二次确认。MCP 的安全模型是"用户确认"，但用户可能不仔细看就点确认

## 十一、总结

MCP 协议核心：

1. **解耦是核心价值**：工具实现一次，所有 MCP Client 可用，不用重复开发
2. **三大能力**：Tools（调用操作）、Resources（读取数据）、Prompts（提示词模板），覆盖模型连接外部世界的所有需求
3. **传输无关**：stdio 本地、HTTP/SSE 远程，根据场景选
4. **安全内置**：用户确认、最小权限、鉴权、审计，防止工具滥用
5. **渐进式能力**：Server 可以只实现部分能力，不用全实现
6. **JSON-RPC 2.0**：基于成熟协议，不用重新发明轮子
7. **生态爆发**：2025年主流 AI 应用都支持 MCP，生态已经成熟

MCP 被称为"AI 时代的 USB-C"——一个标准接口，让大模型能连接各种外部工具和数据。它的价值不在于技术多复杂，而在于**标准化**——结束了每个 AI 应用各自对接工具的混乱局面。对于企业来说，把内部系统和数据封装成 MCP Server，就能让员工用任何 AI 工具安全地访问，这是 AI 落地企业的重要基础设施。
