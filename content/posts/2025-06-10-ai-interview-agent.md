---
title: "AI 模拟面试智能体架构：Go SSE 流式分发与 Prompt 状态机工程"
date: 2025-06-10T14:00:00+08:00
draft: false
tags: ["AI", "智能体", "Go", "SSE", "Prompt工程", "状态机"]
categories: ["AI架构"]
summary: "AI 模拟面试智能体的架构设计，基于 Go SSE 流式分发实现实时对话，用 Prompt 状态机约束面试流程，解决长对话模型失控、流式延迟高、计费闭环等问题。"
keywords: ["AI面试", "智能体", "Go", "SSE", "Prompt状态机"]
---

AI 模拟面试是平台的增值服务，用户和 AI 面试官进行多轮模拟面试，AI 根据用户回答打分并给出改进建议。2025年6月做了智能体架构的重构，今天把设计实践分享出来。

## 一、架构

```text
前端（H5/小程序）→ SSE 长连接 → Go 面试服务 → AI 网关 → 大模型
                              ↓
                        状态机管理 + 对话存储 + 计费扣减
```

## 二、SSE 流式分发

大模型的回答是流式生成的，用 SSE（Server-Sent Events）实时推送给前端，首字响应延迟 < 500ms：

```go
func (h *InterviewHandler) Stream(c *gin.Context) {
    // 设置 SSE 响应头
    c.Header("Content-Type", "text/event-stream")
    c.Header("Cache-Control", "no-cache")
    c.Header("Connection", "keep-alive")

    interviewID := c.Param("id")
    userAnswer := c.PostForm("answer")

    // 1. 状态机推进：根据当前状态决定下一步
    state := h.stateMachine.Next(interviewID, userAnswer)

    // 2. 构建 Prompt
    prompt := h.promptBuilder.Build(state, userAnswer)

    // 3. 调用 AI 网关，流式获取响应
    stream, err := h.aiClient.ChatStream(prompt)
    if err != nil {
        c.SSEvent("error", err.Error())
        return
    }

    // 4. 流式推送给前端
    fullAnswer := ""
    for chunk := range stream {
        fullAnswer += chunk.Content
        c.SSEvent("message", chunk.Content)
        c.Writer.Flush()
    }

    // 5. 流结束，保存对话并更新状态
    h.saveMessage(interviewID, "assistant", fullAnswer)
    h.stateMachine.Update(interviewID, state)

    // 6. 面试结束，生成评分
    if state == "finished" {
        score := h.scoring.Score(interviewID)
        c.SSEvent("score", score)
    }

    c.SSEvent("done", "ok")
}
```

## 三、Prompt 状态机

长对话中模型容易"失控"——跳过流程、问无关问题、提前结束。用状态机约束面试流程：

```text
开始 → 自我介绍 → 技术提问1 → 技术提问2 → 项目经历 → 行为面试 → 反问环节 → 结束评分
```

每个状态对应不同的 Prompt 模板：

```go
type InterviewState string

const (
    StateIntro       InterviewState = "intro"
    StateTech1       InterviewState = "tech_1"
    StateTech2       InterviewState = "tech_2"
    StateProject     InterviewState = "project"
    StateBehavior    InterviewState = "behavior"
    StateReverse     InterviewState = "reverse"
    StateFinished    InterviewState = "finished"
)

func (sm *StateMachine) Next(interviewID string, userAnswer string) InterviewState {
    current := sm.GetCurrentState(interviewID)

    // 根据用户回答质量决定是否推进状态
    // 回答太短或不相关，追问同一个问题
    if len(userAnswer) < 20 {
        return current // 不推进，追问
    }

    // 正常推进到下一个状态
    switch current {
    case StateIntro: return StateTech1
    case StateTech1: return StateTech2
    case StateTech2: return StateProject
    case StateProject: return StateBehavior
    case StateBehavior: return StateReverse
    case StateReverse: return StateFinished
    default: return StateFinished
    }
}
```

每个状态的 Prompt 模板用三层结构锁死模型行为：

```go
func (pb *PromptBuilder) Build(state InterviewState, context string) []Message {
    return []Message{
        // System：强元规则，锁死角色和流程
        {Role: "system", Content: `
你是一位资深的技术面试官，正在进行模拟面试。
严格遵守以下规则：
1. 每次只问一个问题，不要一次问多个
2. 根据用户回答质量决定是否追问，回答太简短要追问细节
3. 不要提前结束面试，必须走完所有流程
4. 语气专业、友好，像真实面试官一样
当前面试阶段：` + string(state) + `
`},
        // User：对话历史 + 当前上下文
        {Role: "user", Content: context},
        // Assistant：预填开场，引导模型按预期回答
        {Role: "assistant", Content: "好的，接下来我会问你关于"},
    }
}
```

System 强元规则 + User 变量 + Assistant 预填（Prefill Injection）三层结构，锁死模型行为，流程越级率降为 0%。

## 四、计费闭环

AI 模拟面试是增值服务，按次或按 Token 计费：

```go
func (h *InterviewHandler) Start(c *gin.Context) {
    userID := c.GetInt64("user_id")

    // 1. 检查会员权限或 Token 余额
    if !h.memberService.HasPermission(userID, "ai_interview") {
        c.JSON(403, gin.H{"code": 403, "message": "请先购买会员或体验卡"})
        return
    }

    // 2. 预扣 Token（面试结束后多退少补）
    h.billingService.PreDeduct(userID, "ai_interview", 5000) // 预扣5000 Token

    // 3. 创建面试会话
    interview := h.interviewService.Create(userID)

    c.JSON(200, gin.H{"code": 0, "interview_id": interview.ID})
}
```

## 五、踩坑经验

1. **SSE 连接超时**：Nginx 默认 60 秒超时，长对话会断开。调大 `proxy_read_timeout` 到 300 秒
2. **模型回答太长**：技术问题模型回答太详细，不像面试官。在 System Prompt 里限制"每次回答不超过3句话"
3. **上下文超长**：多轮对话 Token 超限。用滑动窗口，只保留最近 10 轮对话，更早的摘要压缩
4. **计费不准**：流式响应 Token 统计要等流结束，不能边流边扣。用预扣 + 结算模式

## 六、总结

AI 模拟面试智能体核心：

1. **SSE 流式**：实时推送模型回答，首字延迟 < 500ms，用户体验好
2. **状态机约束**：面试流程状态化，防止模型失控，流程越级率 0%
3. **三层 Prompt**：System 元规则 + User 变量 + Assistant 预填，锁死模型行为
4. **计费闭环**：预扣 + 结算，会员/体验卡/Token 多种计费方式
5. **上下文管理**：滑动窗口 + 摘要压缩，防止 Token 超限
6. **评分系统**：面试结束后 AI 打分，给出改进建议

AI 智能体的核心不是"让模型自由发挥"，而是"用工程手段约束模型在预期范围内行为"。状态机、Prompt 工程、流式分发、计费闭环，这些工程手段才是 AI 产品能商业化落地的关键。
