---
title: "Go context 使用规范：从入门到精通"
date: 2023-08-15T09:00:00+08:00
lastmod: 2023-08-15T09:00:00+08:00
draft: false
author: IYABAO
tags:
  - Go
  - context
categories:
  - 技术
summary: "context 是 Go 并发编程的'信号灯'：超时、取消、传值。但用错 context 反而制造泄漏。这篇文章是团队 context 规范，含官方建议和反模式。"
---

# Go context 使用规范：从入门到精通

Go 的 `context` 是并发编程里最容易被误解的包：有人只用它传值（当 map 用），有人到处 `context.Background()`（等于没用），有人嵌套几十层超时（不知道哪层生效）。这篇文章是我在团队推行的 context 使用规范。

## 一、context 的三种用途

```go
ctx := context.Background()          // 根：所有 context 的起点（只在 main 用）
ctx := context.WithCancel(parent)    // 1. 取消：广播停止信号
ctx := context.WithTimeout(parent, 3*time.Second)  // 2. 超时：到点自动取消
ctx := context.WithValue(parent, key, val)  // 3. 传值：只传请求级数据（少用！）
```

**最重要的一句话**：context 的第一职责是**控制生命周期**（取消/超时），传值是顺手的功能，不是主要用途。

## 二、规范：什么时候用什么

### 入口：用 `context.Background()` 还是 `context.TODO()`

- `Background()`：main / 服务入口，**确定没有更上层 context**
- `TODO()`：代码还没接好 context 时的临时标记（**会 code review 打回**）

```go
// ✅ 服务入口
func main() {
    ctx := context.Background()
    server.Run(ctx)
}

// ❌ 反模式：函数内部凭空造 context
func handler() {
    ctx := context.Background()   // 上层一定有 ctx，为什么不传下来？
    db.Get(ctx, id)
}
```

### 函数签名：context 放第一参数

```go
// ✅ 规范：ctx 永远是第一个参数
func GetUser(ctx context.Context, id int64) (*User, error)

// ❌ 反模式：context 藏在结构体里
type repo struct {
    ctx context.Context   // 存储 ctx = 并发不安全 + 生命周期错乱
}
```

**context 属于调用链，不属于对象**。存进 struct 是 Go 官方明确反对的。

### 传值：只传请求级数据

```go
// ✅ 可以传：请求链路必须的东西
ctx = context.WithValue(ctx, traceIDKey{}, traceID)
ctx = context.WithValue(ctx, userIDKey{}, userID)

// ❌ 禁止传：业务参数（用显式参数）
ctx = context.WithValue(ctx, "city", "杭州")   // 该用参数 city
```

**传值三条铁律**：
1. 只传跨多层的请求级数据（traceID、userID、tenantID）
2. key 用**自定义类型**，不用 string（防冲突）
3. 读到的值要做类型断言 + 判空（别人可能不传）

## 三、超时嵌套：谁生效

```go
// 外层 5s，内层 3s
ctx := context.WithTimeout(parent, 5*time.Second)
ctx2 := context.WithTimeout(ctx, 3*time.Second)
// ctx2 3s 到点 → 取消 → 连带取消 ctx（内层超时提前生效）

// 外层 3s，内层 5s
ctx := context.WithTimeout(parent, 3*time.Second)
ctx2 := context.WithTimeout(ctx, 5*time.Second)
// ctx2 实际还是 3s 就取消（继承父的截止时间）
```

**规则**：**有效的截止时间是所有嵌套里最早的那个**。嵌套超时不是为了叠加，是为了"逐层收敛"。

**实践**：每层调用方设置自己的超时（调用下游前 `WithTimeout`），别依赖上游的——上游可能没传。

## 四、反模式清单（review 红线）

```
❌ context 存 struct / 全局变量
❌ context 传业务参数（城市、分页）
❌ 函数内部 context.Background()（不接上游）
❌ 不检查 ctx.Err()（超时了还继续干活）
❌ 无限嵌套 WithTimeout（层层叠，谁也说不清最终超时）
❌ goroutine 里用父 context 不派生（父取消时子 goroutine 必须能退出）
```

```go
// ❌ 最经典的泄漏：goroutine 用了父 ctx，但没人能取消它
func run() {
    ctx := context.Background()
    go doWork(ctx)   // 这个 goroutine 永远无法被取消
}

// ✅ 必须派生：给子 goroutine 独立取消能力
func run(ctx context.Context) {
    childCtx, cancel := context.WithCancel(ctx)
    defer cancel()
    go doWork(childCtx)
}
```

## 五、实践模板

```go
// 服务间调用的标准姿势
func GetUserByID(ctx context.Context, id int64) (*User, error) {
    // 1. 本层超时（基于上游 ctx）
    ctx, cancel := context.WithTimeout(ctx, 2*time.Second)
    defer cancel()

    // 2. 传递 traceID
    ctx = WithTraceID(ctx, traceIDFrom(ctx))

    // 3. 调用下游（DB/HTTP/RPC），它们自己也会设超时
    return userRepo.Find(ctx, id)
}
```

## 总结

context 使用三句话：

1. **ctx 永远第一参数，永远往下传**，不存对象、不建全局
2. **超时是核心职责**：每层设自己的超时，有效的就是最早那个
3. **传值只传请求级**：traceID/userID，用自定义 key，读到要断言

**context 是调用链的"刹车"**——没有它，一个慢下游能拖死整条链；用好它，每个环节都能按自己的节奏止损。
