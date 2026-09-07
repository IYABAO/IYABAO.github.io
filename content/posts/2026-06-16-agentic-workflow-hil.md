---
title: "Agentic Workflow：人机协作的工程化"
date: 2026-06-16T09:00:00+08:00
lastmod: 2026-06-16T09:00:00+08:00
draft: false
author: IYABAO
tags:
  - Agent
  - 人机协作
  - AI工程
categories:
  - 技术
summary: "全自动 Agent 是理想，人机协作是现实：人在回路、关键节点审批、异常升级、自主度分级——Agentic Workflow 的工程化设计。"
---

# Agentic Workflow：人机协作的工程化

"让 Agent 全自动干活"是很多人的幻想——但生产里，**全自动 = 高风险 = 不敢上线**。现实路径是**人机协作（Human-in-the-Loop）**：Agent 干 80% 的活，人在关键节点把关。这篇文章是 Agentic Workflow 的工程化设计。

## 一、为什么不能全自动

```
全自动 Agent 的风险：
  1. 幻觉：编造数据 → 直接执行 → 事故
  2. 判断错误：误判上下文 → 走错分支
  3. 失控：循环/过度调用/成本爆炸
  4. 责任：出了事谁负责？（AI 不能背锅）

人机协作的价值：
  80% 自动化（提效）
  + 20% 人把关键关（控风险）
```

**核心原则：自主度要和风险匹配。** 低风险任务全自动，高风险任务人在回路。

## 二、自主度分级

| 级别 | 描述 | 适用场景 |
|---|---|---|
| **L1 全自动** | Agent 自主执行到结束 | 低风险（信息检索、格式整理） |
| **L2 自动+汇报** | 自主执行，关键节点汇报 | 中风险（周报生成、数据分析） |
| **L3 建议+审批** | Agent 给方案，人批准后执行 | 高风险（写操作、发消息、下单） |
| **L4 人主导** | 人指挥，Agent 执行 | 关键业务（面试、合同） |

## 三、实现：三个关键机制

### 1. 人在回路（Human-in-the-Loop）

```python
# 关键节点暂停，等人工确认
from langgraph.graph import StateGraph, Command

def high_risk_action(state):
    # 高风险操作：生成方案 → 暂停 → 等人确认
    return Command(
        goto="human_approval",          # 转到人工节点
        update={"proposal": state["proposal"]}
    )

def human_approval(state):
    # 等待人工：approve / reject / edit
    decision = wait_for_human(state["proposal"])
    if decision == "reject":
        return Command(goto="regenerate")    # 重新生成
    return Command(goto="execute")           # 执行
```

**设计要点**：

```
✅ 暂停点要"无副作用"（人确认前什么都没做）
✅ 人能看到"Agent 的推理过程"（为什么这么干）
✅ 人可以选择：批准 / 拒绝 / 修改后执行
✅ 超时处理：无人确认 → 不执行（fail-closed）
```

### 2. 异常升级（Escalation）

```
Agent 遇到以下情况 → 升级给人：
  低置信度（模型自己不确定）
  重复失败（重试 N 次仍失败）
  超出边界（任务超出权限/知识范围）
  冲突检测（和既有事实矛盾）
```

```python
def run_task(task):
    result = agent.execute(task)
    if result.confidence < 0.6:        # 低置信度
        return escalate_to_human(task, result)
    if result.retries >= 3:            # 重复失败
        return escalate_to_human(task, result, reason="retry-exceeded")
    return result
```

### 3. 审批工作流

```
Agent 产出 → 人审批 → 执行 → 回执

审批的三层：
  1. 自动审批：低风险 + 规则匹配（白名单）
  2. 快速审批：单人确认（普通风险）
  3. 多重审批：多人/主管（高风险）
```

## 四、人机协作的产品化

```
Agent 界面三要素：
  1. 进度可视：Agent 现在在干什么（步骤流）
  2. 决策可见：为什么这么选（推理过程）
  3. 干预入口：随时可叫停/改向（人工接管）
```

**关键体验**：

```
✅ Agent 干活时人能看到"过程"（不是黑盒，才能信任）
✅ 审批要"低负担"（一键批准 + 只看关键信息）
✅ 出错可追溯（Agent 每一步有日志，人能复盘）
```

## 五、工程落地清单

```
✅ 自主度分级：任务按风险定级别（L1-L4）
✅ 暂停点设计：无副作用、有上下文、fail-closed
✅ 异常升级：低置信/重试超限/边界外 → 升级
✅ 审批流：自动/快速/多重三级
✅ 全程可观测：步骤、决策、日志
✅ 撤回机制：执行错了能回滚/补救
```

## 六、踩坑记录

1. **审批太频繁**：每步都暂停 → 用户烦 → 只在高风险节点暂停，低风险全自动
2. **人看不懂 Agent 在干嘛**：只给结果不给过程 → 界面展示步骤流 + 决策理由
3. **超时无人理**：卡在审批 2 小时 → 超时自动降级（放弃/重试/通知）
4. **把"建议"当"执行"**：用户点了批准，Agent 又自主扩大了范围 → 批准只授权"建议内"的动作

## 总结

Agentic Workflow 的核心认知：

1. **全自动是理想，人机协作是现实**：自主度匹配风险
2. **三个机制**：人在回路（暂停）、异常升级（兜底）、审批流（授权）
3. **可观测是信任的前提**：看到过程，才敢放手
4. **fail-closed**：没人确认就不执行，宁可慢不可错

**人机协作不是"AI 不行"的妥协，是"AI 可靠"的工程。** 把人的判断力用在关键节点，Agent 的产能用在重复劳动——这才是 2026 年的正确姿势。
