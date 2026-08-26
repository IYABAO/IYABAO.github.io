---
title: "高峰论坛活动系统 2.0：AI 生成议程与智能推荐的技术实现"
date: 2025-09-01T14:00:00+08:00
draft: false
tags: ["活动系统", "AI", "智能推荐", "Go", "议程生成"]
categories: ["架构设计"]
summary: "高峰论坛活动系统 2.0 的技术实现，AI 自动生成活动议程、智能推荐参会者和感兴趣的议题、实时互动问答，提升活动组织效率和参会体验。"
---

每年最佳东方高峰论坛是行业盛会，2025年做了活动系统 2.0 升级，引入 AI 能力——自动生成议程、智能推荐、实时互动问答。今天把技术实现分享出来。

## 一、AI 生成议程

活动组织者输入活动主题、嘉宾名单、时间安排，AI 自动生成完整议程：

```go
func (s *AgendaService) Generate(req *GenerateAgendaRequest) (*Agenda, error) {
    // 1. 构建 Prompt
    prompt := fmt.Sprintf(`
你是一位资深的活动策划专家，请根据以下信息生成高峰论坛议程。

活动主题：%s
活动时间：%s
活动地点：%s
嘉宾名单：%s
议题方向：%s

要求：
1. 议程分上午、下午两个半场，中间有茶歇和午餐
2. 每个嘉宾演讲20-30分钟，包含5分钟问答
3. 安排2个圆桌讨论环节，每个45分钟
4. 开场和结束各有致辞环节
5. 输出JSON格式，包含时间段、环节名称、嘉宾、内容摘要
`, req.Theme, req.Date, req.Location, req.Guests, req.Topics)

    // 2. 调用大模型
    resp, err := s.aiClient.Chat(prompt)
    if err != nil {
        return nil, err
    }

    // 3. 解析 JSON
    var agenda Agenda
    json.Unmarshal([]byte(resp), &agenda)

    // 4. 人工审核后发布
    agenda.Status = "pending_review"
    s.repo.Save(&agenda)
    return &agenda, nil
}
```

AI 生成后人工审核调整，发布后参会者可以在小程序查看议程。

## 二、智能推荐

根据参会者的职位、行业、兴趣，推荐感兴趣的议题和嘉宾：

```go
func (s *RecommendService) Recommend(userID int64, eventID int64) ([]*AgendaItem, error) {
    // 1. 获取用户画像
    profile := s.userService.GetProfile(userID)

    // 2. 获取活动议程
    agenda := s.agendaService.Get(eventID)

    // 3. 计算每个议程项和用户的匹配度
    items := []*AgendaItem{}
    for _, item := range agenda.Items {
        score := 0.0
        // 行业匹配
        if contains(profile.Industries, item.Industry) {
            score += 0.3
        }
        // 职位匹配
        if matchPosition(profile.Position, item.TargetPosition) {
            score += 0.2
        }
        // 兴趣标签匹配（用向量相似度）
        score += vectorSimilarity(profile.Interests, item.Tags) * 0.3
        // 热度加权
        score += item.Popularity * 0.2

        items = append(items, &AgendaItem{Item: item, Score: score})
    }

    // 4. 按匹配度排序，返回 Top 5
    sort.Slice(items, func(i, j int) bool { return items[i].Score > items[j].Score })
    return items[:min(5, len(items))], nil
}
```

## 三、实时互动问答

活动现场参会者可以扫码提问，AI 辅助筛选和整理问题：

```go
// 提问
func (s *QAService) Ask(userID int64, question string, agendaItemID int64) error {
    // 1. AI 审核问题（过滤违规内容）
    if !s.aiClient.Moderate(question) {
        return errors.New("问题包含违规内容")
    }

    // 2. AI 提取问题关键词和分类
    analysis := s.aiClient.AnalyzeQuestion(question)

    // 3. 存入问题池
    qa := &QA{
        UserID: userID,
        Question: question,
        AgendaItemID: agendaItemID,
        Keywords: analysis.Keywords,
        Category: analysis.Category,
        Status: "pending",
    }
    s.repo.Save(qa)

    // 4. 发布到实时频道（主持人端实时看到）
    s.websocket.Broadcast("qa_new", qa)
    return nil
}

// 主持人端：AI 合并相似问题，推荐提问顺序
func (s *QAService) OrganizeQuestions(agendaItemID int64) ([]*QA, error) {
    questions := s.repo.GetPending(agendaItemID)

    // AI 聚类相似问题
    clusters := s.aiClient.ClusterQuestions(questions)

    // 每个聚类选点赞最多的问题，按热度排序
    var organized []*QA
    for _, cluster := range clusters {
        best := cluster[0]
        for _, q := range cluster {
            if q.Likes > best.Likes {
                best = q
            }
        }
        best.MergedCount = len(cluster)
        organized = append(organized, best)
    }
    sort.Slice(organized, func(i, j int) bool { return organized[i].Likes > organized[j].Likes })
    return organized, nil
}
```

## 四、踩坑经验

1. **AI 生成议程格式不稳定**：大模型有时不按 JSON 格式输出。加了格式校验 + 重试机制，最多重试3次，仍失败则返回结构化模板让人工填写
2. **推荐冷启动**：新用户没有画像，推荐不准。用活动注册时填写的行业和职位做基础推荐，后续根据行为数据优化
3. **实时问答延迟**：活动现场网络差，WebSocket 连接不稳定。加了离线提问（本地缓存，网络恢复后同步）和降级方案（短信提问）
4. **AI 审核误判**：AI 内容审核有时误判正常问题。加了人工复核机制，被 AI 拦截的问题进入审核队列，人工确认后放行

## 五、总结

高峰论坛活动系统 2.0 核心：

1. **AI 生成议程**：大模型根据活动信息自动生成议程，人工审核后发布，提升策划效率
2. **智能推荐**：基于用户画像和向量相似度，推荐感兴趣的议题和嘉宾
3. **实时互动**：扫码提问 + AI 审核聚类 + 主持人端实时展示，提升互动体验
4. **AI 辅助**：议程生成、问题审核、相似问题聚类，AI 做辅助，人工做决策
5. **降级方案**：AI 失败有兜底，网络差有离线模式，保证活动正常进行

AI 在活动系统里的定位是"辅助工具"，不是"替代人工"。AI 生成初稿、做筛选和整理，最终决策由人来做。这样既能提升效率，又能保证质量和可控性。
