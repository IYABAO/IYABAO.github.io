---
title: "Go 错误处理：从 if err != nil 到错误设计"
date: 2023-03-14T09:00:00+08:00
lastmod: 2023-03-14T09:00:00+08:00
draft: false
author: IYABAO
tags:
  - Go
  - 错误处理
categories:
  - 技术
summary: "Go 的错误处理不是'写 if err != nil'，是'设计错误'：错误分类、包装链、哨兵错误、错误码与日志——一套让错误'可定位、可分类、可恢复'的体系。"
---

# Go 错误处理：从 if err != nil 到错误设计

"Go 的错误处理就是到处写 `if err != nil`"——这是新手认知。生产级 Go 的错误处理是**错误设计**：错误怎么分类、怎么包装、怎么传递、怎么记录。这篇文章是我从"会写"到"会设计"的完整总结。

## 一、错误的三个问题

```
问题 1：错误没有上下文
  "connection refused" —— 哪个服务？哪次调用？什么参数？

问题 2：错误没有分类
  网络错误（可重试）和参数错误（重试也没用）混在一起

问题 3：错误没有流向
  底层错误直接透传给上层/前端 → 暴露内部细节 / 用户看不懂
```

## 二、错误包装（上下文）

```go
// Go 1.13+ 错误包装（%w）
func GetOrder(ctx, id) (*Order, error) {
    order, err := repo.Find(id)
    if err != nil {
        return nil, fmt.Errorf("获取订单失败 id=%s: %w", id, err)
    }
    return order, nil
}

// 排查时：errors.Is / errors.As 逐层解包
// "获取订单失败 id=abc: dial tcp 10.0.0.1:3306: connection refused"
// ↑ 一眼看到：哪个操作、哪个参数、底层原因
```

**规范**：

```
✅ 每层包装：fmt.Errorf("操作 + 关键参数: %w", err)
✅ 关键参数进错误（订单 ID、用户 ID）——排查不用翻日志
❌ 只透传 err（没有上下文，等于没说）
❌ 吞错误（err 忽略）——最坏的写法
```

## 三、错误分类（可恢复 vs 不可恢复）

```go
// 定义错误类型（分类）
type BizError struct {
    Code    int    // 业务错误码
    Message string // 用户可读
    Retryable bool // 是否可重试
}

var (
    ErrNotFound     = &BizError{40400, "资源不存在", false}
    ErrConflict     = &BizError{40900, "状态冲突", true}
    ErrUpstreamDown = &BizError{50300, "上游服务不可用", true}
)

// 处理策略不同：
//   ErrNotFound → 返回 404（正常业务分支）
//   ErrConflict → 重试/提示用户
//   ErrUpstreamDown → 熔断降级
```

**分类的价值**：**上层根据分类做不同处理**（重试/降级/提示/告警），而不是"所有错误一律 500"。

## 四、错误流向设计

```
底层（repo/dao）：原始错误 + 上下文包装
中间层（service）：业务错误分类（BizError）
上层（handler）：映射 HTTP 状态码 + 用户可读信息
```

```go
// handler 层
func GetOrderHandler(c *gin.Context) {
    order, err := svc.GetOrder(c, id)
    if err != nil {
        var be *BizError
        if errors.As(err, &be) {
            c.JSON(be.Code, gin.H{"code": be.Code, "msg": be.Message})
            return
        }
        // 未分类错误：日志 + 通用 500（不暴露细节）
        log.Error("未分类错误", "err", err, "id", id)
        c.JSON(500, gin.H{"code": 50000, "msg": "系统繁忙"})
        return
    }
    c.JSON(200, order)
}
```

**原则**：

```
✅ 用户只看到"可读信息"（不暴露堆栈/内部细节）
✅ 内部错误必须记日志（带完整上下文）
✅ 未分类错误兜底：500 + 日志（别让内部细节漏到前端）
```

## 五、错误与日志的配合

```go
// 记日志的规范
log.Error("获取订单失败",
    "err", err,            // 完整错误链
    "order_id", id,        // 关键参数
    "trace_id", traceID,   // 链路
    "user_id", uid,        // 用户维度
)

// 关键：ERROR 日志必须"可行动"
//  看了知道：什么问题、影响谁、怎么处理
```

## 六、避坑清单

```
✅ 每层包装（操作 + 参数 + %w）
✅ 错误分类（BizError + Retryable）
✅ 分层流向（底层上下文 → 中层分类 → 上层映射）
✅ 日志带全上下文（err + 参数 + trace_id）
❌ 别吞错误（err != nil 时忽略）
❌ 别裸透传（底层错误直接回前端）
❌ 别用 panic 控制业务流（panic 只留给"不该发生的事"）
```

## 七、实战：一个完整的错误示例

```go
// repo 层
func (r *Repo) FindOrder(ctx, id) (*Order, error) {
    row := r.db.First(&Order{}, id)
    if errors.Is(row.Error, gorm.ErrRecordNotFound) {
        return nil, fmt.Errorf("订单不存在 id=%s: %w", id, ErrNotFound)
    }
    if row.Error != nil {
        return nil, fmt.Errorf("查询订单失败 id=%s: %w", id, row.Error)
    }
    return &Order{}, nil
}

// 排查体验：
//  前端看到：404 资源不存在
//  日志看到：查询订单失败 id=abc: dial tcp ...（完整链路）
//  运维知道：可以重试 or 查数据库连通性
```

## 总结

Go 错误处理的核心认知：

1. **包装**：每层加"操作 + 参数"，用 %w 保留链
2. **分类**：BizError + Retryable，上层差异化处理
3. **流向**：底层上下文 → 中层分类 → 上层映射
4. **日志**：错误必须可行动（带全上下文）

**"if err != nil" 是语法，错误设计才是能力。** 一个项目错误处理好不好，决定了凌晨两点被叫起来排查时是"5 分钟定位"还是"翻一小时日志"。
