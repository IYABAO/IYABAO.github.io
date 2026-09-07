---
title: "Agent 工具调用：从 Function Calling 到 MCP"
date: 2026-05-05T09:00:00+08:00
lastmod: 2026-05-05T09:00:00+08:00
draft: false
author: IYABAO
tags:
  - Agent
  - 工具调用
  - MCP
categories:
  - 技术
summary: "Agent 的核心能力是'会调用工具'。Function Calling 的机制、工具描述如何影响选型、从私有函数到 MCP 标准化——Agent 工具调用的完整演进与工程实践。"
---

# Agent 工具调用：从 Function Calling 到 MCP

Agent 和 Chatbot 的本质区别：**Agent 会"动手"**——调用工具、读写数据、执行动作。工具调用（Tool Calling / Function Calling）是 Agent 的核心机制。这篇文章从机制讲起，到工程实践，到 MCP 标准化。

## 一、Function Calling 的机制

**核心流程**：LLM 决定"该调哪个工具、传什么参数"，系统执行，结果回填。

```
用户：查一下今天的杭州天气
  │
  ▼
LLM 推理：需要调用 get_weather(city="杭州", date="今天")
  │
  ▼  （LLM 输出结构化工具调用请求）
系统执行：weather_api.get_weather("杭州", "2026-05-05") → {温度: 28, 晴}
  │
  ▼  （结果回填）
LLM 组织回答：今天杭州 28 度，晴，适合出行。
```

**注意**：**LLM 只"决定"调用，不"执行"调用**——执行是系统的责任。LLM 输出的是：工具名 + 参数（结构化 JSON）。

## 二、工具的定义：名称、描述、参数

工具怎么定义，直接决定 LLM 能不能用对：

```json
{
  "type": "function",
  "function": {
    "name": "search_resume",
    "description": "在简历库中检索候选人。按关键词匹配技能/经历/职位。",
    "parameters": {
      "type": "object",
      "properties": {
        "query": {
          "type": "string",
          "description": "检索关键词，如'Go 后端 3 年经验'"
        },
        "limit": {
          "type": "integer",
          "description": "返回条数，默认 10，最大 50"
        }
      },
      "required": ["query"]
    }
  }
}
```

**三个关键**：

```
1. name：LLM 用它选工具（清晰、语义化）
2. description：LLM 判断"这个工具适不适合当前任务"（写清楚能力边界）
3. parameters：LLM 按描述填参数（描述决定填得对不对）
```

**我的经验**：**工具描述是给 LLM 看的文档**——"检索简历"和"在简历库中按技能/经历/职位关键词匹配，返回候选人和匹配度"，后者让 LLM 选得更准。

## 三、工程实践：工具调用的正确姿势

### 1. 结果结构要"LLM 友好"

```json
// 错误：返回一堆无关字段，LLM 不知道该提取什么
// 正确：结构清晰 + 字段名语义化
{
  "candidates": [
    {"name": "张三", "skills": ["Go", "K8s"], "match_score": 92},
    {"name": "李四", "skills": ["PHP"], "match_score": 65}
  ],
  "total": 87
}
```

### 2. 错误要"可重试"

```json
// 工具失败返回的错误，LLM 要能理解并重试/换方式
{"error": "参数非法: date 格式应为 YYYY-MM-DD"}
{"error": "上游超时，请重试"}
{"error": "无权限访问该资源"}
```

### 3. 多轮工具调用（Agent 的"思考链"）

```
用户：帮我分析张三适不适合后端岗位
  → 调用 search_resume("张三")
  → 结果：找到简历
  → 调用 get_resume_detail("id-123")     // 需要更多信息
  → 结果：工作经历
  → LLM 综合分析 → 输出结论
```

**允许多轮工具调用**：LLM 可以连续调多个工具（每次调用结果回填上下文，LLM 决定下一步）。

### 4. 工具循环的安全

```
✅ 最大调用轮数（默认 5-10 轮，防止死循环）
✅ 每轮工具调用都审计
✅ 高成本/写操作工具：二次确认
✅ 工具结果注入上下文 → 注意 Prompt 注入（工具返回里藏指令）
```

## 四、从 Function Calling 到 MCP

```
Function Calling：模型 API 的特性（每个厂商格式不同）
  问题：工具和模型绑定、换模型要重写、工具不可复用

MCP：标准化工具协议
  工具定义（schema）→ MCP 标准格式
  工具调用 → MCP 协议（Client ↔ Server）
  好处：一套工具，所有模型/应用复用
```

**演进关系**：

```
Function Calling = 机制（模型怎么表达"我要调工具"）
MCP = 协议（工具怎么标准化地提供和调用）

生产实践：模型层用 Function Calling 机制，
         工具层用 MCP 协议（Server 定义 + Client 接入）
```

## 五、选型建议

| 场景 | 方案 |
|---|---|
| 单模型快速开发 | 直接用 Function Calling（最简） |
| 多模型/多应用复用工具 | MCP（标准化） |
| 企业级工具治理 | MCP + 鉴权 + 审计 |
| 纯本地小工具 | Function Calling + 简单函数映射 |

**我的实践**：AI 面试产品早期用 Function Calling（快），后期工具多了、要复用了（Best 东方 Skills 给外部 LLM 用），迁到 MCP——**机制不变，协议标准化**。

## 六、踩坑记录

1. **描述写得太简**：LLM 不知道该不该用这工具 → 描述写"能力 + 边界 + 示例"
2. **参数校验在 LLM 侧做**：LLM 传错参数就报错 → 系统侧宽松解析 + 纠错（日期格式自动归一）
3. **工具结果过长**：塞进上下文 token 爆炸 → 结果裁剪（只回 Top N + 摘要）
4. **并行工具调用滥用**：一次调 10 个 → 改成"只调相关的 1-3 个"（LLM 靠描述判断）

## 总结

工具调用的核心认知：

1. **机制**：LLM 决定"调什么、传什么"，系统执行"真调用"
2. **定义质量决定效果**：名称清晰、描述写全、参数描述准
3. **多轮调用是 Agent 的本质**：连续工具调用 = 解决问题的过程
4. **MCP 是工具层的标准化**：Function Calling 是机制，MCP 是协议

**Agent 的能力边界 = 工具集的能力边界。** 会定义工具、会管理调用循环、会用 MCP 标准化——这是 AI 应用工程师的核心技能。
