---
title: "LangGraph 多智能体协作：招聘场景 Multi-Agent 编排实践"
date: 2026-02-14T14:00:00+08:00
draft: false
tags: ["LangGraph", "Multi-Agent", "AI Agent", "大模型", "招聘", "编排", "Python"]
categories: ["AI架构"]
summary: "基于 LangGraph 的多智能体协作系统实践，涵盖 Agent 角色设计、状态机编排、工具调用、人机协作、记忆管理，以及在招聘场景（AI 面试官+简历分析师+匹配专家）中的实战应用和效果评估。"
---

单个 AI Agent 能力有限，复杂任务需要多个 Agent 协作完成。2026年初我们用 LangGraph 搭建了招聘场景的多智能体系统——AI 面试官、简历分析师、匹配专家、HR 助手四个 Agent 协作，完成从简历筛选到面试评估的全流程。今天把完整的实践经验分享出来。

## 一、为什么需要 Multi-Agent

单个大模型虽然能力强，但在复杂业务场景中有局限：

1. **上下文有限**：一个 Agent 处理所有任务，上下文容易溢出，信息丢失
2. **角色不聚焦**：既要分析简历又要面试又要评估，角色混乱，输出质量下降
3. **工具太多**：一个 Agent 挂几十个工具，模型选择工具容易出错
4. **无法并行**：单 Agent 串行执行，耗时久
5. **缺乏协作**：复杂任务需要不同专业视角的"讨论"和"辩论"，单 Agent 做不到

Multi-Agent 的思路是：**把复杂任务拆成多个子任务，每个子任务由专门的 Agent 负责，Agent 之间通过消息传递协作完成整体任务**。

类比真实团队：
- 简历分析师：负责筛选和分析简历
- 匹配专家：负责评估简历和职位的匹配度
- AI 面试官：负责模拟面试和提问
- HR 助手：负责整体协调、生成报告、和用户交互

四个角色各司其职，协作完成招聘全流程。

## 二、LangGraph 简介

LangGraph 是 LangChain 团队推出的**有状态图编排框架**，专门用于构建多 Agent 系统和复杂工作流。

**核心概念**：
- **State（状态）**：图的共享状态，所有节点都能读写，是 Agent 间传递信息的载体
- **Node（节点）**：图中的处理单元，可以是一个 Agent、一个函数、一个工具调用
- **Edge（边）**：节点之间的连接，定义执行流程
- **Conditional Edge（条件边）**：根据状态动态决定下一个节点，实现分支和循环
- **Supervisor（监督者）**：一个中心 Agent 协调其他 Agent 的执行

**为什么选 LangGraph**：
1. **有状态**：内置状态管理，Agent 间共享信息方便
2. **灵活编排**：支持顺序、分支、循环、并行，能表达复杂工作流
3. **人机协作**：内置 interrupt 机制，支持人工介入
4. **持久化**：支持检查点（checkpoint），工作流可以暂停和恢复
5. **LangChain 生态**：和 LangChain 的工具、模型、记忆组件无缝集成
6. **Python/JS 双语言**：支持 Python 和 JavaScript/TypeScript

## 三、系统架构

### 整体流程

```text
用户提交简历和职位
       │
       ▼
┌─────────────┐
│  HR 助手     │ ← 协调者，和用户交互
│  (Supervisor)│
└──────┬──────┘
       │
       ├──────────┬──────────┐
       ▼          ▼          ▼
┌──────────┐ ┌──────────┐ ┌──────────┐
│简历分析师 │ │ 匹配专家  │ │AI 面试官  │
│(Analyst) │ │(Matcher)  │ │(Interview)│
└────┬─────┘ └────┬─────┘ └────┬─────┘
     │             │             │
     └─────────────┼─────────────┘
                   ▼
            ┌─────────────┐
            │  评估汇总    │
            │ (Evaluator)  │
            └──────┬──────┘
                   ▼
            生成招聘评估报告
```

### 四个 Agent 角色

**1. HR 助手（Supervisor）**
- 职责：和用户交互、协调其他 Agent、汇总结果、生成报告
- 工具：调用其他 Agent、文件读写、邮件发送
- 特点：不做专业分析，只做协调和沟通

**2. 简历分析师（Analyst）**
- 职责：解析简历、提取结构化信息、分析候选人优势劣势、识别简历疑点
- 工具：简历解析 API、技能标准化、学历验证
- 输出：结构化简历数据 + 分析报告

**3. 匹配专家（Matcher）**
- 职责：评估简历和职位的匹配度，多维度打分，给出匹配建议
- 工具：职位 JD 解析、技能匹配、薪资匹配、向量相似度计算
- 输出：匹配度评分 + 各维度分析 + 匹配建议

**4. AI 面试官（Interviewer）**
- 职责：根据简历和职位生成面试问题，模拟面试对话，评估候选人回答
- 工具：问题生成、对话管理、回答评估
- 输出：面试问题清单 + 模拟面试记录 + 面试评估

## 四、LangGraph 实现

### 定义共享状态

```python
from typing import TypedDict, List, Dict, Optional, Annotated
from langgraph.graph.message import add_messages

class RecruitmentState(TypedDict):
    # 输入
    resume_text: str                    # 原始简历文本
    job_description: str               # 职位描述
    user_id: str                       # 用户ID

    # 各 Agent 输出
    structured_resume: Optional[Dict]  # 结构化简历
    resume_analysis: Optional[str]     # 简历分析报告
    match_score: Optional[float]       # 匹配度总分
    match_analysis: Optional[Dict]     # 匹配度各维度分析
    interview_questions: Optional[List] # 面试问题清单
    interview_record: Optional[List]    # 模拟面试记录
    interview_evaluation: Optional[str]  # 面试评估

    # 协调
    messages: Annotated[List, add_messages]  # 对话消息
    current_step: str                  # 当前步骤
    human_feedback: Optional[str]      # 人工反馈
    final_report: Optional[str]        # 最终报告
```

状态是所有 Agent 共享的"黑板"，每个 Agent 读取需要的输入，写入自己的输出。

### 定义 Agent 节点

```python
from langchain.chat_models import init_chat_model
from langchain_core.messages import SystemMessage, HumanMessage

llm = init_chat_model("claude-3-5-sonnet-20241022", model_provider="anthropic")

def resume_analyst_node(state: RecruitmentState) -> RecruitmentState:
    """简历分析师节点：解析简历，提取结构化信息，分析优劣势"""

    system_prompt = """
    你是一位资深的简历分析师，有10年以上HR经验。
    请分析以下简历，完成：
    1. 提取结构化信息（基本信息、工作经历、教育背景、技能）
    2. 分析候选人的优势和劣势
    3. 识别简历中的疑点（如时间断层、描述模糊、夸大嫌疑）
    4. 给出简历改进建议

    输出 JSON 格式，包含 structured_resume 和 analysis 两个字段。
    """

    response = llm.invoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=f"简历内容：\n{state['resume_text']}")
    ])

    # 解析输出，更新状态
    parsed = parse_json(response.content)
    return {
        "structured_resume": parsed["structured_resume"],
        "resume_analysis": parsed["analysis"],
        "current_step": "resume_analysis_done"
    }

def match_expert_node(state: RecruitmentState) -> RecruitmentState:
    """匹配专家节点：评估简历和职位的匹配度"""

    system_prompt = """
    你是一位招聘匹配专家，擅长评估候选人与职位的匹配度。
    请根据结构化简历和职位描述，从以下维度评估：
    1. 技能匹配（权重40%）
    2. 经验匹配（权重25%）
    3. 学历匹配（权重15%）
    4. 薪资匹配（权重10%）
    5. 文化匹配（权重10%）

    每个维度给0-100分和简要说明，最后计算加权总分。
    给出匹配等级（A/B/C/D）和推荐建议。
    """

    response = llm.invoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=f"""
        结构化简历：{state['structured_resume']}
        职位描述：{state['job_description']}
        """)
    ])

    parsed = parse_json(response.content)
    return {
        "match_score": parsed["total_score"],
        "match_analysis": parsed,
        "current_step": "match_analysis_done"
    }

def interviewer_node(state: RecruitmentState) -> RecruitmentState:
    """AI 面试官节点：生成面试问题，模拟面试"""

    system_prompt = """
    你是一位资深的技术面试官。
    请根据简历和职位要求，生成面试问题：
    1. 自我介绍引导（1题）
    2. 技术深度问题（3-5题，针对简历中的项目和技能）
    3. 系统设计问题（1-2题，针对职位要求）
    4. 行为面试问题（2题）
    5. 候选人反问环节引导

    每个问题要说明考察点和期望回答方向。
    """

    response = llm.invoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=f"""
        简历分析：{state['resume_analysis']}
        职位描述：{state['job_description']}
        匹配度分析：{state['match_analysis']}
        """)
    ])

    return {
        "interview_questions": parse_json(response.content),
        "current_step": "interview_questions_ready"
    }
```

### 定义图和边

```python
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

# 构建图
workflow = StateGraph(RecruitmentState)

# 添加节点
workflow.add_node("hr_supervisor", hr_supervisor_node)
workflow.add_node("resume_analyst", resume_analyst_node)
workflow.add_node("match_expert", match_expert_node)
workflow.add_node("interviewer", interviewer_node)
workflow.add_node("evaluator", evaluator_node)
workflow.add_node("report_generator", report_generator_node)

# 设置入口
workflow.set_entry_point("hr_supervisor")

# 定义边（顺序执行）
workflow.add_edge("hr_supervisor", "resume_analyst")
workflow.add_edge("resume_analyst", "match_expert")
workflow.add_edge("match_expert", "interviewer")

# 条件边：匹配度低于阈值，跳过面试，直接评估
def should_do_interview(state: RecruitmentState) -> str:
    if state["match_score"] and state["match_score"] < 50:
        return "skip_interview"
    return "do_interview"

workflow.add_conditional_edges(
    "interviewer",
    should_do_interview,
    {
        "do_interview": "evaluator",
        "skip_interview": "evaluator",
    }
)

workflow.add_edge("evaluator", "report_generator")
workflow.add_edge("report_generator", END)

# 编译图，加检查点（支持暂停恢复）
checkpointer = MemorySaver()
app = workflow.compile(checkpointer=checkpointer)
```

### 人机协作（Human-in-the-loop）

关键节点加入人工审核，用 LangGraph 的 interrupt 机制：

```python
from langgraph.types import interrupt

def evaluator_node(state: RecruitmentState) -> RecruitmentState:
    """评估汇总节点：汇总各 Agent 输出，人工审核后生成报告"""

    # 汇总各 Agent 的分析结果
    summary = f"""
    【简历分析】{state['resume_analysis']}
    【匹配度评估】总分 {state['match_score']}分
    {state['match_analysis']}
    【面试问题】已生成 {len(state['interview_questions'])} 道问题
    """

    # 中断，等待人工审核
    human_decision = interrupt({
        "type": "review",
        "message": "请审核以下评估汇总，确认或修改：",
        "summary": summary,
        "options": ["确认", "修改后继续", "重新评估"]
    })

    if human_decision == "确认":
        return {"current_step": "evaluation_confirmed"}
    elif human_decision == "重新评估":
        return {"current_step": "re_evaluate"}
    else:
        return {"human_feedback": human_decision, "current_step": "evaluation_modified"}
```

运行时，图执行到 evaluator 节点会暂停，等待人工输入：

```python
# 启动工作流
config = {"configurable": {"thread_id": "recruitment-001"}}
result = app.invoke({
    "resume_text": resume_text,
    "job_description": job_desc,
    "user_id": "user-001"
}, config)

# 工作流暂停在人工审核节点，获取当前状态
state = app.get_state(config)
print(state.next)  # ('evaluator',)

# 人工审核后，恢复执行
result = app.invoke(None, config)  # 传入人工决策
```

### 并行执行

简历分析和匹配分析可以并行执行，用 LangGraph 的 Send API：

```python
from langgraph.types import Send

def hr_supervisor_node(state: RecruitmentState):
    """HR 助手：启动并行分析"""
    # 同时启动简历分析和匹配分析（并行）
    return [
        Send("resume_analyst", state),
        Send("match_expert", state),
    ]
```

两个 Agent 并行执行，都完成后再进入下一步，总耗时减少约 40%。

## 五、Agent 间通信模式

Multi-Agent 系统中，Agent 间通信有几种模式：

### 1. 共享状态（黑板模式）

所有 Agent 读写同一个 State，这是 LangGraph 的默认模式。适合信息需要被多个 Agent 共享的场景。

优点：简单，信息共享方便
缺点：状态可能被意外修改，需要约定读写规则

### 2. 消息传递（点对点）

Agent 之间直接发消息，类似真实团队的沟通：

```python
# AI 面试官向简历分析师提问
interviewer_message = {
    "from": "interviewer",
    "to": "analyst",
    "content": "候选人的项目经历描述比较模糊，能帮我详细分析一下吗？",
    "type": "question"
}
```

适合需要 Agent 间"讨论"和"辩论"的场景。

### 3. 监督者模式（Supervisor）

一个中心 Agent 协调其他 Agent，决定谁执行、执行什么、什么时候汇总：

```python
def supervisor_node(state: RecruitmentState):
    """监督者：决定下一步做什么"""
    # 根据当前状态决定下一个 Agent
    if not state["structured_resume"]:
        return "resume_analyst"
    elif not state["match_score"]:
        return "match_expert"
    elif state["match_score"] >= 50 and not state["interview_questions"]:
        return "interviewer"
    else:
        return "evaluator"
```

适合流程复杂、需要动态决策的场景。

我们的系统用了**混合模式**：共享状态传递数据 + 监督者协调流程 + 关键节点人工介入。

## 六、记忆管理

Multi-Agent 系统中，记忆管理很重要：

### 短期记忆

- 用 State 存储当前工作流的所有信息
- 工作流结束后，State 可以持久化到数据库

### 长期记忆

- 每个 Agent 有自己的长期记忆（历史对话、用户偏好、历史评估）
- 用向量数据库存储，检索相关历史作为上下文

```python
# 面试面试官的长期记忆
interviewer_memory = VectorStoreRetriever(
    vectorstore=milvus,
    search_kwargs={"k": 5, "filter": {"agent": "interviewer"}}
)

# 面试时检索历史面试记录
history = interviewer_memory.get_relevant_documents(
    f"类似职位的面试问题和评估 {state['job_description']}"
)
```

### 上下文管理

- 每个 Agent 只加载自己需要的上下文，不要把整个 State 都传给 LLM
- 长对话用滑动窗口，只保留最近 N 轮
- 历史对话用摘要压缩，减少 token 占用

## 七、效果评估

系统上线后，和单 Agent 方案对比：

| 指标 | 单 Agent | Multi-Agent | 提升 |
|------|---------|-------------|------|
| 简历分析准确率 | 75% | 90% | +20% |
| 匹配度评估准确率 | 70% | 88% | +26% |
| 面试问题质量 | 72分 | 88分 | +22% |
| 评估报告完整性 | 65% | 92% | +42% |
| 平均处理时间 | 3分钟 | 2分钟 | -33%（并行） |
| 用户满意度 | 7.2/10 | 8.8/10 | +22% |

Multi-Agent 在质量和效率上都明显优于单 Agent，特别是复杂任务的处理质量提升显著。

## 八、踩坑经验

1. **Agent 角色定义不清**：初期 Agent 职责重叠，输出混乱。每个 Agent 要有明确的职责边界、输入输出定义、系统提示词，角色越聚焦输出质量越高
2. **状态膨胀**：State 里字段越来越多，传递给 LLM 时上下文溢出。每个 Agent 只加载需要的字段，不要把整个 State 都传进去
3. **循环死锁**：条件边设计不好，Agent 之间可能循环调用不终止。加最大步数限制和超时机制，超过限制强制终止
4. **工具选择错误**：一个 Agent 挂太多工具，模型容易选错工具。每个 Agent 只挂自己需要的工具（5-10个），不要贪多
5. **人工介入时机**：人工介入太多，自动化程度低；介入太少，错误不能及时发现。关键决策点（评估确认、报告生成前）介入，常规步骤自动执行
6. **成本控制**：多 Agent 调用 LLM 次数多，token 消耗大。用便宜的模型做简单任务（如信息提取），贵的模型做复杂任务（如面试评估），成本降低 50%
7. **可观测性**：多 Agent 系统调试困难，不知道哪个 Agent 出了问题。加完整的日志和追踪（LangSmith），每个 Agent 的输入输出、耗时、token 消耗都要记录
8. **幻觉传播**：一个 Agent 的幻觉输出可能被其他 Agent 当作事实继续传播。每个 Agent 的输出都要做校验，关键数据要和原始信息交叉验证

## 九、总结

LangGraph Multi-Agent 实践核心：

1. **角色拆分是基础**：把复杂任务拆成多个专业角色，每个 Agent 职责单一、聚焦，输出质量更高
2. **共享状态是黑板**：State 是 Agent 间传递信息的载体，设计好 State 结构是关键
3. **灵活编排是优势**：LangGraph 支持顺序、分支、循环、并行、条件边，能表达复杂工作流
4. **人机协作是保障**：关键节点加入人工审核，interrupt 机制让工作流可暂停可恢复
5. **监督者模式常用**：中心 Agent 协调其他 Agent，动态决定执行流程，适合复杂任务
6. **记忆管理不能少**：短期记忆用 State，长期记忆用向量数据库，上下文管理控制 token 消耗
7. **可观测性是调试关键**：多 Agent 系统复杂，完整的日志和追踪是排查问题的基础
8. **成本控制要考虑**：多 Agent token 消耗大，按任务复杂度选模型，简单任务用便宜模型
9. **质量提升明显**：Multi-Agent 比单 Agent 在复杂任务上质量提升 20-40%，效率也因并行而提升

Multi-Agent 是 AI 应用从"玩具"走向"生产力工具"的关键技术。单个 Agent 只能做简单任务，复杂的业务流程需要多个专业 Agent 协作。LangGraph 提供了强大的编排能力，让 Multi-Agent 系统的构建变得可控、可调试、可维护。但记住，Multi-Agent 不是银弹——简单任务用单 Agent 就够了，只有任务足够复杂、需要多专业视角协作时，Multi-Agent 的优势才会体现。
