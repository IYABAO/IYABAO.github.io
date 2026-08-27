---
title: "从 MCP 到 Agent Skills：AI 能力封装的演进路径与最佳实践"
date: 2026-06-18T14:00:00+08:00
draft: false
tags: ["MCP", "Agent Skills", "AI能力封装", "大模型", "工具调用", "AI架构"]
categories: ["AI架构"]
summary: "AI 能力封装从 MCP 到 Agent Skills 的演进路径，涵盖 MCP 协议原理、Skills 概念、两者关系、封装方法论、设计原则，以及在企业级 AI 应用中的实践和选型建议。"
---

AI 应用的核心是"大模型 + 工具"，但工具怎么封装、怎么管理、怎么复用，一直是个问题。从早期的 Function Calling，到 MCP 协议，再到现在的 Agent Skills，AI 能力封装在不断演进。2026年我们深度实践了从 MCP 到 Agent Skills 的能力封装体系，今天把演进路径和最佳实践分享出来。

## 一、AI 能力封装的演进

### 阶段1：Function Calling（2023）

OpenAI 推出 Function Calling，让大模型能调用外部函数：

```python
# 定义函数
functions = [
    {
        "name": "get_weather",
        "description": "获取天气",
        "parameters": {
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "城市"}
            },
            "required": ["city"]
        }
    }
]

# 调用模型
response = openai.ChatCompletion.create(
    model="gpt-4",
    messages=messages,
    functions=functions
)
```

**问题**：
- 函数定义和代码耦合，难以复用
- 每个应用自己定义函数，没有标准
- 函数只能在当前应用用，不能跨应用共享
- 没有版本管理、权限控制、审计

### 阶段2：MCP 协议（2024-2025）

Anthropic 推出 MCP（Model Context Protocol），标准化大模型和外部工具的连接：

```
┌──────────┐         MCP 协议          ┌──────────────┐
│  大模型   │ ◄──────────────────────► │  MCP Server  │
│ (Client) │   JSON-RPC over stdio/HTTP│  (Tools)     │
└──────────┘                            └──────────────┘
```

MCP 的核心概念：
- **Tools**：工具，大模型可以调用的函数
- **Resources**：资源，大模型可以读取的数据（如文件、数据库记录）
- **Prompts**：提示词模板，可复用的 Prompt
- **Client**：大模型端（如 Claude Desktop、Cursor）
- **Server**：工具端，提供 Tools/Resources/Prompts

MCP 的优势：
- **标准化**：统一协议，任何支持 MCP 的客户端都能连接任何 MCP Server
- **解耦**：工具和应用解耦，MCP Server 独立部署和维护
- **可复用**：一个 MCP Server 可以被多个客户端使用
- **生态丰富**：官方和社区有几千个 MCP Server

### 阶段3：Agent Skills（2025-2026）

MCP 解决了"连接"问题，但没有解决"能力组合"问题。一个复杂的 AI Agent 需要多个工具组合、有状态、有流程，MCP 的单个 Tool 不够用。

Agent Skills 是更高层次的能力封装：

> **Skill = 一组相关的 Tools + Resources + Prompts + 工作流 + 领域知识**

一个 Skill 是一个完整的"能力包"，比如：
- **简历分析 Skill**：包含简历解析工具、技能标准化工具、匹配度评估 Prompt、分析工作流
- **代码审查 Skill**：包含代码读取工具、静态分析工具、安全扫描工具、审查 Prompt、审查流程
- **部署 Skill**：包含构建工具、测试工具、部署工具、回滚工具、部署工作流

Skills 和 MCP 的关系：
- **MCP 是连接层**：标准化大模型和工具的连接协议
- **Skills 是能力层**：在 MCP 之上，把多个工具组合成完整的能力包
- **Skills 可以用 MCP 实现**：一个 Skill 可以包含一个或多个 MCP Server

## 二、MCP 深度解析

### MCP 协议原理

MCP 基于 JSON-RPC 2.0，支持两种传输方式：
- **stdio**：标准输入输出，适合本地工具（如文件系统、Shell）
- **HTTP/SSE**：HTTP 长连接，适合远程服务（如数据库、SaaS API）

核心交互流程：

```
1. 初始化（Initialize）
   Client → Server：初始化请求，声明支持的能力
   Server → Client：初始化响应，返回 Server 信息和能力

2. 工具列举（Tools/List）
   Client → Server：请求工具列表
   Server → Client：返回所有工具的定义（名称、描述、参数）

3. 工具调用（Tools/Call）
   Client → Server：调用工具，传入参数
   Server → Client：返回工具执行结果

4. 资源读取（Resources/Read）
   Client → Server：读取资源
   Server → Client：返回资源内容

5. 提示词获取（Prompts/Get）
   Client → Server：获取提示词模板
   Server → Client：返回提示词
```

### MCP Server 开发

用 Python 开发一个简单的 MCP Server：

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("resume-analyzer")

@mcp.tool()
def parse_resume(resume_text: str) -> dict:
    """解析简历，提取结构化信息
    
    Args:
        resume_text: 简历文本内容
        
    Returns:
        结构化的简历信息，包含基本信息、工作经历、教育背景、技能
    """
    # 调用简历解析服务
    result = resume_parser.parse(resume_text)
    return result

@mcp.tool()
def calculate_match(resume: dict, job_description: str) -> dict:
    """计算简历和职位的匹配度
    
    Args:
        resume: 结构化简历
        job_description: 职位描述
        
    Returns:
        匹配度评分和各维度分析
    """
    result = matcher.calculate(resume, job_description)
    return result

@mcp.resource("resume://{id}")
def get_resume(id: str) -> str:
    """获取简历资源"""
    return resume_store.get(id)

@mcp.prompt()
def interview_question(resume_summary: str, job: str) -> str:
    """生成面试问题的提示词模板"""
    return f"""基于以下简历和职位，生成5个面试问题：
    简历：{resume_summary}
    职位：{job}
    """

if __name__ == "__main__":
    mcp.run()
```

FastMCP 是 Anthropic 官方的 Python MCP 框架，用装饰器定义 Tool/Resource/Prompt，简单高效。

### MCP 的局限

MCP 很强大，但也有局限：

1. **单个 Tool 粒度细**：MCP 的 Tool 是单个函数，复杂任务需要多次调用，大模型需要自己编排调用顺序
2. **没有状态管理**：MCP 是无状态的，每次调用独立，复杂的多步骤任务需要客户端自己管理状态
3. **没有工作流**：MCP 不支持定义工作流（如"先解析简历，再计算匹配度，最后生成报告"）
4. **没有领域知识**：MCP Server 只提供工具，不包含领域知识和最佳实践
5. **组合困难**：多个 MCP Server 之间的工具组合需要客户端自己处理

这些局限正是 Agent Skills 要解决的。

## 三、Agent Skills 深度解析

### 什么是 Agent Skill

Agent Skill 是一个完整的能力包，包含：

| 组成部分 | 说明 | 示例（简历分析 Skill） |
|---------|------|---------------------|
| **Tools** | 工具集合 | 简历解析、技能标准化、匹配度计算 |
| **Resources** | 数据资源 | 简历库、职位库、技能词典 |
| **Prompts** | 提示词模板 | 简历分析 Prompt、面试问题生成 Prompt |
| **Workflows** | 工作流定义 | 简历分析流程（解析→标准化→匹配→报告） |
| **Knowledge** | 领域知识 | 简历分析最佳实践、行业技能标准 |
| **Memory** | 记忆管理 | 历史分析记录、用户偏好 |
| **Config** | 配置 | API Key、模型选择、参数调优 |

一个 Skill 是"即插即用"的能力包，AI Agent 加载 Skill 后就能完成一类任务，不用自己编排工具和流程。

### Skill 的工作原理

```
┌─────────────────────────────────────────┐
│              AI Agent                    │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐ │
│  │ Skill A │  │ Skill B │  │ Skill C │ │
│  │(简历分析)│  │(代码审查)│  │(部署)   │ │
│  └────┬────┘  └────┬────┘  └────┬────┘ │
└───────┼─────────────┼─────────────┼──────┘
        │             │             │
        ▼             ▼             ▼
   工作流引擎      工作流引擎     工作流引擎
        │             │             │
        ▼             ▼             ▼
   MCP Tools     MCP Tools     MCP Tools
```

Agent 加载 Skill 后：
1. Skill 注册自己的 Tools/Resources/Prompts 到 Agent
2. Skill 定义工作流，告诉 Agent 这类任务的标准流程
3. 用户请求任务时，Agent 选择合适的 Skill
4. Skill 的工作流引擎编排工具调用，完成任务
5. Skill 管理状态和记忆，确保多步骤任务正确执行

### Skill 开发示例

用 Python 开发一个简历分析 Skill：

```python
from agent_skills import Skill, Tool, Workflow, step

class ResumeAnalysisSkill(Skill):
    """简历分析 Skill：解析简历、评估匹配度、生成分析报告"""
    
    name = "resume-analysis"
    description = "简历分析和职位匹配能力包"
    version = "1.0.0"
    
    # 定义工具
    tools = [
        Tool(
            name="parse_resume",
            description="解析简历文本，提取结构化信息",
            function=self.parse_resume
        ),
        Tool(
            name="standardize_skills",
            description="标准化技能名称，映射到统一技能词典",
            function=self.standardize_skills
        ),
        Tool(
            name="calculate_match",
            description="计算简历和职位的匹配度",
            function=self.calculate_match
        ),
        Tool(
            name="generate_report",
            description="生成简历分析报告",
            function=self.generate_report
        )
    ]
    
    # 定义工作流
    workflow = Workflow(
        name="resume_analysis",
        description="简历分析完整流程",
        steps=[
            step("parse_resume", input="resume_text", output="resume"),
            step("standardize_skills", input="resume", output="standardized_resume"),
            step("calculate_match", input=["standardized_resume", "job_description"], output="match_result"),
            step("generate_report", input=["standardized_resume", "match_result"], output="report")
        ]
    )
    
    # 领域知识（作为 Prompt 的一部分）
    knowledge = """
    简历分析最佳实践：
    1. 工作经历要按时间倒序，重点看最近3年
    2. 技能要区分"精通"和"了解"，不要只看关键词
    3. 项目经历要关注规模（团队大小、用户量、数据量）
    4. 教育背景要区分学历和学校，不要唯学历论
    5. 注意简历中的时间断层和描述模糊的地方
    """
    
    def parse_resume(self, resume_text: str) -> dict:
        # 调用简历解析服务
        return resume_parser.parse(resume_text)
    
    def standardize_skills(self, resume: dict) -> dict:
        # 标准化技能
        return skill_standardizer.standardize(resume)
    
    def calculate_match(self, resume: dict, job_description: str) -> dict:
        # 计算匹配度
        return matcher.calculate(resume, job_description)
    
    def generate_report(self, resume: dict, match_result: dict) -> str:
        # 生成报告（用大模型）
        prompt = f"""基于以下信息生成简历分析报告：
        简历：{resume}
        匹配度：{match_result}
        领域知识：{self.knowledge}
        """
        return llm.generate(prompt)

# 注册 Skill 到 Agent
agent.register_skill(ResumeAnalysisSkill())
```

## 四、MCP vs Skills：怎么选

| 维度 | MCP | Agent Skills |
|------|-----|-------------|
| 定位 | 连接协议 | 能力封装 |
| 粒度 | 单个 Tool/Resource/Prompt | 一组工具+工作流+知识 |
| 状态 | 无状态 | 有状态（工作流、记忆） |
| 工作流 | 不支持 | 支持（定义多步骤流程） |
| 领域知识 | 不包含 | 包含（最佳实践、行业知识） |
| 复用性 | 跨客户端复用 | 跨 Agent 复用 |
| 生态 | 成熟（几千个 Server） | 新兴（标准还在形成） |
| 适用场景 | 单一工具、简单任务 | 复杂任务、多步骤流程 |

**选型建议**：

1. **简单工具用 MCP**：如文件读写、数据库查询、API 调用，单个工具就能完成，用 MCP
2. **复杂能力用 Skills**：如简历分析、代码审查、部署发布，需要多个工具组合、有流程、有领域知识，用 Skills
3. **Skills 可以包含 MCP**：一个 Skill 内部可以用 MCP Server 提供工具，Skill 负责编排和封装
4. **渐进式演进**：先用 MCP 封装单个工具，等工具多了、流程复杂了，再抽象成 Skills

**我们的实践**：
- 底层工具用 MCP 封装（数据库、文件、API）
- 上层能力用 Skills 封装（简历分析、AI 面试、代码审查）
- Skills 内部调用 MCP Tools，Skill 负责编排工作流和注入领域知识
- 形成"MCP 工具层 + Skills 能力层"的两层架构

## 五、Skill 设计原则

### 1. 单一职责

一个 Skill 只做一类事，不要做"万能 Skill"。

- ✅ 好：简历分析 Skill、代码审查 Skill、部署 Skill
- ❌ 坏：全能开发 Skill（什么都做，什么都做不好）

### 2. 高内聚低耦合

Skill 内部的工具、工作流、知识要紧密相关，Skill 之间尽量独立。

- 高内聚：简历分析 Skill 里的工具都是简历分析相关的
- 低耦合：简历分析 Skill 不依赖代码审查 Skill

### 3. 可组合

Skills 之间可以组合使用，完成更复杂的任务。

- 例如：简历分析 Skill + AI 面试 Skill + 评估报告 Skill，组合成完整的招聘流程
- Skill 之间通过标准接口通信，不直接依赖

### 4. 可配置

Skill 应该可配置，适应不同场景。

- 模型选择（用 Claude 还是 GPT）
- 参数调优（温度、最大 token）
- 流程定制（哪些步骤可选）
- 知识更新（领域知识可热更新）

### 5. 可观测

Skill 的执行过程要可观测，方便调试和优化。

- 日志：每个步骤的输入输出、耗时、token 消耗
- 追踪：工作流执行链路，哪个步骤慢、哪个步骤失败
- 指标：成功率、平均耗时、成本、用户满意度

### 6. 安全可控

Skill 执行要有安全控制，防止滥用和风险。

- 权限控制：Skill 能访问哪些资源、调用哪些工具
- 审批机制：高风险操作（如删除、部署）需要人工审批
- 沙箱执行：不可信的 Skill 在沙箱中执行
- 审计日志：所有操作记录日志，可追溯

## 六、实践经验

### 1. 从 MCP 开始，逐步抽象

不要一开始就设计复杂的 Skills，先用 MCP 封装工具，用一段时间后，发现哪些工具经常组合使用、有固定流程，再抽象成 Skill。

我们的简历分析 Skill 就是这样来的：
- 一开始有 5 个 MCP Tool（解析、标准化、匹配、报告、存储）
- 每次分析简历都要按固定顺序调用这 5 个工具
- 大模型有时会调错顺序或漏掉步骤
- 于是把这 5 个工具 + 固定流程 + 领域知识封装成 ResumeAnalysisSkill
- 之后 Agent 只要调用 Skill，就能完成完整的简历分析

### 2. Skill 粒度要适中

Skill 太大（万能 Skill）难以维护和复用，太小（单个工具）又失去了封装的意义。

我们的经验：
- 一个 Skill 包含 3-10 个工具
- 一个 Skill 对应一个完整的业务场景
- 一个 Skill 的工作流有 3-8 个步骤
- 一个 Skill 可以被 2 个以上的 Agent 使用

### 3. 领域知识是 Skill 的核心价值

工具和工作流可以复制，但领域知识是 Skill 的核心竞争力。

- 简历分析 Skill 的价值不是"调用解析 API"，而是"知道怎么分析简历、怎么评估匹配度、怎么写报告"
- 代码审查 Skill 的价值不是"调用静态分析工具"，而是"知道审查什么、怎么判断严重程度、怎么给改进建议"
- 把团队的经验和最佳实践沉淀到 Skill 的领域知识里，这才是真正的复用

### 4. 持续迭代优化

Skill 不是一次写完就完事，要持续迭代：

- 收集使用数据（哪些步骤经常失败、哪个工具耗时最长）
- 收集用户反馈（哪里不好用、缺少什么功能）
- 更新领域知识（行业变化、最佳实践更新）
- 优化工作流（调整步骤、增加分支、优化参数）
- 版本管理（Skill 有版本号，升级不影响现有使用）

## 七、未来趋势

AI 能力封装的演进方向：

1. **Skill 市场**：出现 Skill 应用商店，开发者可以发布和下载 Skills，类似 npm/App Store
2. **Skill 组合编排**：高级编排工具，把多个 Skills 组合成复杂的 Agent 工作流
3. **Skill 自动生成**：大模型根据需求自动生成 Skill（工具定义、工作流、知识）
4. **Skill 标准化**：Skills 的标准协议和格式形成，跨平台兼容
5. **Skill 安全沙箱**：Skill 执行的安全沙箱成熟，不可信 Skill 也能安全执行
6. **Skill 经济**：Skill 开发者可以收费，形成 Skill 经济生态
7. **企业级 Skill 平台**：企业内部的 Skill 管理平台，包含开发、测试、发布、权限、审计

## 八、总结

从 MCP 到 Agent Skills 核心：

1. **演进路径清晰**：Function Calling（函数）→ MCP（连接协议）→ Agent Skills（能力包），抽象层次越来越高
2. **MCP 是连接层**：标准化大模型和工具的连接，适合单一工具和简单任务，生态成熟
3. **Skills 是能力层**：在 MCP 之上封装完整能力（工具+工作流+知识+记忆），适合复杂任务和多步骤流程
4. **两者互补不冲突**：MCP 提供工具，Skills 编排工具，形成"MCP 工具层 + Skills 能力层"的两层架构
5. **Skill 设计六原则**：单一职责、高内聚低耦合、可组合、可配置、可观测、安全可控
6. **领域知识是核心价值**：工具和流程可复制，领域知识（最佳实践、行业经验）才是 Skill 的竞争力
7. **从 MCP 开始逐步抽象**：不要一开始就设计复杂 Skills，先用 MCP 封装工具，用一段时间后再抽象成 Skills
8. **未来是 Skill 生态**：Skill 市场、自动生成、标准化、安全沙箱、企业平台，Skills 会成为 AI 应用的核心组件

AI 应用的竞争，未来不是模型的竞争，而是能力封装的竞争——谁能把领域知识和最佳实践封装成高质量的 Skills，谁就能在 AI 时代胜出。MCP 是基础，Skills 是未来，现在开始投入，提前布局。
