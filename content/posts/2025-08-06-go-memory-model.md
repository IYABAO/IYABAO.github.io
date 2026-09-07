---
title: "Go 内存模型：happens-before 与并发安全"
date: 2025-08-06T09:00:00+08:00
lastmod: 2025-08-06T09:00:00+08:00
draft: false
author: IYABAO
tags:
  - Go
  - 内存模型
  - 并发
categories:
  - 技术
summary: "为什么不加锁的并发读可能读到旧值？Go 内存模型的 happens-before 规则、可见性、数据竞争——并发编程的地基，比 goroutine 语法重要得多。"
---

# Go 内存模型：happens-before 与并发安全

goroutine 和 channel 语法谁都会，但**并发正确性**要靠内存模型理解。为什么一个 goroutine 改了变量，另一个 goroutine 读到的还是旧值？为什么明明"顺序执行"的代码会出诡异结果？——答案都在 Go 内存模型里。

## 一、问题场景

```go
var flag bool
var data int

// goroutine A
go func() {
    data = 42          // 1
    flag = true        // 2
}()

// goroutine B
go func() {
    for !flag {        // 3
        runtime.Gosched()
    }
    fmt.Println(data)  // 4 可能打印 0！不是 42
}()

// 直觉：A 先写 data 再写 flag，B 看到 flag=true 后 data 一定是 42
// 现实：B 可能打印 0 —— 为什么？
```

**原因**：没有同步机制时，两个 goroutine 之间**没有 happens-before 关系**——编译器/CPU 可能重排，B 的缓存可能看不到 A 的写入。

## 二、happens-before：核心概念

**定义**：事件 E1 happens-before E2，当且仅当 E1 的影响对 E2 可见（且顺序保证）。

Go 官方内存模型规定了**哪些操作建立 happens-before 关系**：

| 同步操作 | 建立的规则 |
|---|---|
| **channel** | 向 channel 发送 happens-before 从该 channel 接收完成 |
| **sync.Mutex** | Unlock happens-before 后续的 Lock |
| **sync.WaitGroup** | Wait 返回 happens-before 所有 Add 的 Done 之后 |
| **sync.Once** | doOnce 内函数 happens-before 所有 Once.Do 返回 |
| **goroutine 创建** | go 语句 happens-before 新 goroutine 开始执行 |
| **goroutine 退出** | goroutine 退出 happens-before 它被 Join（如有） |

**修复上面的例子**：用 channel 建立顺序：

```go
done := make(chan struct{})
go func() {
    data = 42
    close(done)      // 发送/关闭 happens-before 接收方看到
}()
<-done              // 接收完成
fmt.Println(data)   // 保证是 42
```

## 三、为什么互斥锁能"顺便"解决可见性

```go
var mu sync.Mutex
var data int

// A
mu.Lock()
data = 42
mu.Unlock()      // Unlock happens-before ...

// B
mu.Lock()        // ... 后续的 Lock
fmt.Println(data)  // 保证看到 42
defer mu.Unlock()
```

**锁的价值不只是互斥，还建立内存屏障**：A 的 Unlock 之前的所有写入，对 B 的 Lock 之后的所有读取可见。**这就是为什么"加锁的代码天然无可见性问题"**——锁顺带完成了内存同步。

## 四、数据竞争（Data Race）

**定义**：两个 goroutine 同时访问同一变量，且至少一个是写操作，且没有同步机制 → 数据竞争。

**数据竞争的危害**（Go 官方原话）：**未定义行为**——可能读到撕裂值、可能死循环、可能 panic，行为不可预测。

```go
// 经典数据竞争
var counter int
for i := 0; i < 1000; i++ {
    go func() { counter++ }()   // 1000 个 goroutine 并发写
}
// 结果可能是 1000，可能是 997，可能是任何数
```

## 五、检测：-race 是必须的

```bash
go test -race ./...
go build -race -o app .
# 生产跑带 race 的版本（性能降 ~5-10 倍，仅测试用）
```

**race detector 是 Go 最强的并发检测工具**——它不能保证 100% 抓全（只在测试覆盖到的执行路径生效），但**跑了它没报，比不跑强一百倍**。

**CI 必开**：

```yaml
# GitHub Actions 中
- run: go test -race ./...
```

## 六、Go 1.22 起 memory model 的增强

Go 1.22 更新了内存模型文档（官方），明确了：

1. **sync/atomic 的更强保证**：`atomic.Int32` 等类型有明确语义
2. **channel 关闭的 happen-before 保证更清晰**
3. **跨 package 的 sync 原语保证**：第三方并发原语（如 errgroup）基于官方原语，保证可推导

**结论**：写并发代码用官方同步原语（channel/mutex/atomic），语义有保证；自己造轮子（unsafe 指针、手动内存序）容易踩未定义行为。

## 七、实用规范

```
✅ 共享变量必须同步：锁 / channel / atomic 三选一
✅ 永远跑 -race（本地 + CI）
✅ channel 是 Go 推荐的通信方式（先考虑）
✅ atomic 用于计数器/标志位（性能敏感）
✅ 别用不安全的内存操作（unsafe.Pointer 只在极端场景）
```

```go
// 生产规范示例：共享状态用 atomic
type Server struct {
    requests atomic.Int64    // 计数器：atomic 足够
    cfg      atomic.Pointer[Config]  // 配置热更新：原子指针
}
// 状态流转用 channel / mutex
```

## 总结

Go 内存模型的三大认知：

1. **没有 happens-before 就没有可见性**：两 goroutine 之间要有同步操作才保证"看见"
2. **锁 = 互斥 + 内存屏障**：加锁代码天然解决可见性
3. **数据竞争是未定义行为**：`-race` 是底线，不是可选项

**并发编程的正确姿势：用官方原语建立 happens-before，别靠"直觉顺序"。** goroutine 语法 10 分钟学会，内存模型是让你 10 年不踩坑的地基。
