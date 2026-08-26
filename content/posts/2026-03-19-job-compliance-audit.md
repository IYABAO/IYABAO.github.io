---
title: "职位描述合规性校验：基于规则引擎的内容安全审核方案"
date: 2026-03-19T14:00:00+08:00
draft: false
tags: ["内容安全", "规则引擎", "合规", "Go", "AI审核"]
categories: ["架构设计"]
summary: "职位描述合规性校验系统的设计，基于规则引擎 + AI 审核，实现职位发布前的自动内容安全审核，覆盖虚假招聘、薪资不符、歧视性要求、违规词汇等场景，降低平台合规风险。"
---

招聘平台的职位描述需要合规审核，防止虚假招聘、薪资欺诈、歧视性要求、违规词汇等问题。早期靠人工审核，效率低且容易漏。2026年3月做了基于规则引擎的自动合规校验系统，今天把方案分享出来。

## 一、审核场景

| 场景 | 说明 | 风险等级 |
|------|------|---------|
| 虚假招聘 | 职位描述与实际不符，骗取简历 | 高 |
| 薪资不符 | 写的薪资范围与市场严重偏离 | 中 |
| 歧视性要求 | 性别、年龄、地域、健康歧视 | 高 |
| 违规词汇 | 涉黄、涉赌、涉毒、政治敏感 | 高 |
| 联系方式 | 职位描述里留私人联系方式（绕过平台） | 中 |
| 重复发布 | 同一企业重复发布相同职位 | 低 |

## 二、规则引擎设计

用 Go 写了轻量级规则引擎，支持配置化规则：

```go
// 规则定义
type Rule struct {
    ID          string        `json:"id"`
    Name        string        `json:"name"`
    Category    string        `json:"category"`    // 违规分类
    RiskLevel   string        `json:"risk_level"`  // high/medium/low
    Condition   string        `json:"condition"`   // 条件表达式
    Action      string        `json:"action"`      // reject/warn/manual
    Message     string        `json:"message"`     // 提示信息
    Enabled     bool          `json:"enabled"`
}

// 审核上下文
type AuditContext struct {
    Title       string
    Description string
    SalaryMin   int
    SalaryMax   int
    CompanyID   int64
    CompanyName string
    CityID      int
    Position    string
}
```

### 规则示例

```json
[
  {
    "id": "discrimin_gender",
    "name": "性别歧视",
    "category": "discrimination",
    "risk_level": "high",
    "condition": "contains(description, '限男性') || contains(description, '限女性') || contains(description, '男士优先')",
    "action": "reject",
    "message": "职位描述包含性别歧视性要求，请修改后重新发布"
  },
  {
    "id": "salary_abnormal",
    "name": "薪资异常",
    "category": "fraud",
    "risk_level": "medium",
    "condition": "salary_max > 100000 && position != 'CEO' && position != 'CTO'",
    "action": "manual",
    "message": "薪资范围异常，需人工审核"
  },
  {
    "id": "contact_info",
    "name": "联系方式",
    "category": "violation",
    "risk_level": "medium",
    "condition": "regex_match(description, '1[3-9]\\d{9}') || regex_match(description, '[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}')",
    "action": "warn",
    "message": "职位描述包含联系方式，建议删除，求职者可通过平台联系"
  }
]
```

### 规则执行

```go
func (e *RuleEngine) Execute(ctx *AuditContext) *AuditResult {
    result := &AuditResult{Passed: true}

    for _, rule := range e.rules {
        if !rule.Enabled {
            continue
        }

        // 执行条件表达式
        matched, err := e.eval(rule.Condition, ctx)
        if err != nil {
            log.Errorf("rule %s eval error: %v", rule.ID, err)
            continue
        }

        if matched {
            result.Violations = append(result.Violations, Violation{
                RuleID: rule.ID,
                RuleName: rule.Name,
                Category: rule.Category,
                RiskLevel: rule.RiskLevel,
                Message: rule.Message,
            })

            // 根据 action 决定是否通过
            switch rule.Action {
            case "reject":
                result.Passed = false
                result.FinalAction = "reject"
            case "manual":
                result.NeedManual = true
            case "warn":
                result.Warnings = append(result.Warnings, rule.Message)
            }
        }
    }

    return result
}
```

## 三、AI 辅助审核

规则引擎覆盖不了语义层面的违规（如隐晦的歧视、虚假描述），用大模型做辅助审核：

```go
func (s *AIAuditService) Audit(ctx *AuditContext) (*AIAuditResult, error) {
    prompt := fmt.Sprintf(`
你是一位招聘平台内容审核专家，请审核以下职位描述是否合规。

职位标题：%s
薪资范围：%d-%d
职位描述：
%s

请检查以下方面：
1. 是否包含虚假招聘信息（与职位严重不符的描述）
2. 是否包含歧视性要求（性别、年龄、地域、健康、婚育）
3. 是否包含违规词汇（涉黄、涉赌、涉毒、政治敏感）
4. 是否包含诱导性内容（骗取费用、押金、培训费）
5. 是否包含绕过平台的联系方式

请以JSON格式返回：
{
  "passed": true/false,
  "risk_level": "high/medium/low/none",
  "violations": [{"category": "...", "reason": "...", "suggestion": "..."}],
  "summary": "审核结论"
}
`, ctx.Title, ctx.SalaryMin, ctx.SalaryMax, ctx.Description)

    resp, err := s.aiClient.Chat(prompt)
    if err != nil {
        return nil, err
    }

    var result AIAuditResult
    json.Unmarshal([]byte(resp), &result)
    return &result, nil
}
```

## 四、审核流程

```
职位发布 → 规则引擎审核 → AI 辅助审核 → 结果判定
                ↓              ↓
            高风险拒绝     中风险人工审核
            低风险警告     低风险直接通过
```

```go
func (s *AuditService) Audit(job *Job) *AuditResult {
    ctx := &AuditContext{
        Title: job.Title,
        Description: job.Description,
        SalaryMin: job.SalaryMin,
        SalaryMax: job.SalaryMax,
        CompanyID: job.CompanyID,
        CityID: job.CityID,
    }

    // 1. 规则引擎审核（快，毫秒级）
    ruleResult := s.ruleEngine.Execute(ctx)
    if ruleResult.FinalAction == "reject" {
        return ruleResult // 高风险直接拒绝
    }

    // 2. AI 辅助审核（慢，秒级，只对规则通过或人工审核的调用）
    if ruleResult.NeedManual || ruleResult.Passed {
        aiResult, err := s.aiService.Audit(ctx)
        if err == nil && aiResult.RiskLevel == "high" {
            ruleResult.Passed = false
            ruleResult.FinalAction = "reject"
            ruleResult.Violations = append(ruleResult.Violations, aiResult.Violations...)
        }
    }

    return ruleResult
}
```

## 五、踩坑经验

1. **规则误判**："男士优先"在某些特定岗位（如男更衣室管理员）是合理的，但规则会一刀切拒绝。加了白名单岗位，特定岗位跳过性别歧视规则
2. **AI 审核不稳定**：大模型审核结果有时不一致，同样的内容两次审核结果不同。加了温度=0 + 多次审核取多数，提高稳定性
3. **性能问题**：每个职位都调 AI 审核，成本高且慢。规则引擎先过滤，只有规则通过或需人工审核的才调 AI，降低 80% 的 AI 调用量
4. **规则维护**：违规手法不断变化，规则要持续更新。建立了规则运营流程，运营人员可以配置规则，不用开发介入

## 六、总结

职位描述合规校验核心：

1. **规则引擎**：配置化规则，快速审核常见违规，毫秒级响应
2. **AI 辅助**：大模型审核语义层面的违规，覆盖规则引擎盲区
3. **分层审核**：规则先过滤，AI 再补充，高风险拒绝，中风险人工，低风险通过
4. **持续运营**：规则和 AI 模型持续迭代，应对新的违规手法
5. **可解释性**：每个审核结果都有明确的违规原因和修改建议，用户知道怎么改
6. **性能优化**：规则引擎快、AI 慢，分层调用降低成本和延迟

内容安全审核是平台的生命线，出问题可能导致下架甚至法律风险。规则引擎 + AI 审核的组合方案，既能保证覆盖率，又能控制成本和延迟。核心是"规则兜底 + AI 补充 + 人工终审"，三层防护确保合规。
