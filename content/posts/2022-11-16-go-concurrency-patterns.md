---
title: "Go 并发模式：goroutine + channel 实战"
date: 2022-11-16T09:00:00+08:00
lastmod: 2022-11-16T09:00:00+08:00
draft: false
author: IYABAO
tags:
  - Go
  - 并发
  - goroutine
categories:
  - 技术
summary: "不要用锁解决问题，用通信。Worker Pool、Fan-out/Fan-in、超时控制、优雅退出——Go 并发编程的四个高频模式，每个都附可直接用的代码。"
---

# Go 并发模式：goroutine + channel 实战

Go 并发编程第一原则：**不要通过共享内存来通信，而要通过通信来共享内存。** 这篇文章不是讲语法，是讲四个生产里真正高频的并发模式，每个都有可直接抄的代码。

## 一、Worker Pool：控制并发度

```go
// 场景：1000 个简历要解析，控制并发 20
func workerPool(ctx context.Context, jobs []Job, workers int) []Result {
    jobsCh := make(chan Job)
    results := make([]Result, len(jobs))

    var wg sync.WaitGroup
    wg.Add(workers)
    for i := 0; i < workers; i++ {
        go func() {
            defer wg.Done()
            for job := range jobsCh {
                r := process(ctx, job)   // 每个 worker 循环消费
                results[job.ID] = r
            }
        }()
    }

    go func() {
        defer close(jobsCh)
        for _, j := range jobs {
            select {
            case jobsCh <- j:
            case <-ctx.Done():
                return   // 取消时停止派发
            }
        }
    }()

    wg.Wait()
    return results
}
```

**要点**：worker 数量 = 下游能力（DB 连接池、ES 并发上限），不是越大越好。**channel 关闭只能由发送方做**，否则 panic。

## 二、Fan-out / Fan-in：拆解再汇总

```go
// Fan-out：一个任务流拆成多路处理
func fanOut(ctx context.Context, source <-chan Item, n int) []<-chan Result {
    channels := make([]<-chan Result, 0, n)
    for i := 0; i < n; i++ {
        ch := make(chan Result)
        channels = append(channels, ch)
        go func(out chan Result) {
            for item := range source {
                out <- process(item)
            }
            close(out)
        }(ch)
    }
    return channels
}

// Fan-in：多路结果汇聚成一路
func fanIn(channels ...<-chan Result) <-chan Result {
    out := make(chan Result)
    var wg sync.WaitGroup
    for _, ch := range channels {
        wg.Add(1)
        go func(c <-chan Result) {
            defer wg.Done()
            for r := range c {
                out <- r
            }
        }(ch)
    }
    go func() { wg.Wait(); close(out) }()
    return out
}
```

**典型场景**：一个用户请求要并行查简历、查职位、查收藏（3 个下游），Fan-out 并发查、Fan-in 汇总，总耗时 = 最慢的那个而不是三者之和。

## 三、超时控制：context 的正确用法

```go
// 所有下游调用都要带超时
func getUserWithTimeout(ctx context.Context) (*User, error) {
    ctx, cancel := context.WithTimeout(ctx, 500*time.Millisecond)
    defer cancel()
    // 注意：子 ctx 超时后，父 ctx 不受影响
    return userRepo.Get(ctx, id)
}
```

**错误示范**（漏了超时）：

```go
// ❌ 没有超时的调用：下游挂了，这里永远阻塞，goroutine 泄漏
func bad() {
    user := <-userCh
    _ = user
}
```

**规范**：**每个 RPC / DB / 网络调用必须带超时**，这是 Go 项目 review 的第一条红线。泄漏的 goroutine 不报错、不崩溃，只是慢慢吃光内存——最阴险的故障。

## 四、优雅退出：主从协作

```go
// 服务关闭时，正在处理的任务要让它跑完
func runServer(ctx context.Context) {
    ctx, cancel := context.WithCancel(ctx)
    defer cancel()

    done := make(chan struct{})
    go func() {
        defer close(done)
        // 消费任务，ctx.Done() 时停止接收
        for {
            select {
            case task := <-taskCh:
                process(task)
            case <-ctx.Done():
                return   // 收到退出信号，处理完当前任务退出
            }
        }
    }()

    // 监听系统信号
    sig := make(chan os.Signal, 1)
    signal.Notify(sig, syscall.SIGTERM, syscall.SIGINT)
    <-sig
    cancel()       // 广播取消
    <-done         // 等所有 worker 优雅退出
}
```

**为什么重要**：直接 `os.Exit` 会丢正在处理的任务（比如已收到但没落库的投递）。优雅退出 = 当前任务跑完 + 新任务不接 + 资源释放。

## 五、并发陷阱清单

| 陷阱 | 表现 | 解法 |
|---|---|---|
| goroutine 泄漏 | 内存缓慢上涨 | 所有 goroutine 都要有退出路径（ctx） |
| 并发写 map | fatal error: concurrent map writes | 用 `sync.Map` 或锁，或 channel 串行化 |
| channel 关闭 panic | send on closed channel | 只有发送方关闭，接收方绝不关 |
| 死锁 | 全 goroutine 阻塞 | channel 缓冲 + 超时 select |
| 共享变量竞争 | 数据错乱 | `go test -race` 必开 |

**`go test -race` 是底线**：并发代码不跑 race 检测等于没测。

## 总结

Go 并发的核心认知：

1. **控制并发度**：Worker Pool，数量跟下游走
2. **拆分汇总**：Fan-out/Fan-in 把串行变并行
3. **超时是红线**：ctx 不传超时 = 泄漏定时炸弹
4. **优雅退出**：取消信号 → 处理完当前 → 再退出
5. **race 必检**：`-race` 是并发的体检仪

**goroutine 是廉价的，但泄漏是昂贵的。** 每个 `go func` 都要能回答一个问题：**它什么时候退出？**
