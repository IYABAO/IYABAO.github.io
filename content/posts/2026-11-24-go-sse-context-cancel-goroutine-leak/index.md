---
title: "客户端断开后，我的 goroutine 还在跑：一次 SSE 流式网关 context 取消失效的排查"
date: 2026-11-24T05:00:00+08:00
draft: false
tags: ["Go", "并发", "context", "SSE", "LLM 网关", "踩坑记录", "pprof"]
categories: ["技术复盘"]
description: "压测时客户端主动断开，网关的 goroutine 数却不降反升，几小时后内存翻倍。根因不是 channel 没关，而是 context 取消信号只传导到了 handler，没传导到那个真正卡在 channel 发送上的生产协程。这篇用一份最小复现、一次 pprof 现场，讲清楚 Go 流式网关里取消信号应该怎么传、三个最常见的断链点，以及一张能直接抄的排查清单。"
---

> 本文所有地址、端口、账号、令牌均已泛化，命令行为说明问题的骨架。涉及的是一类通用的 Go 并发缺陷，与任何具体的线上系统无关。

## 现象：客户端都走了，goroutine 数还在涨

事情是从一张再普通不过的监控图开始的。

那是一个给大模型做流式转发的网关，协议是 SSE（Server-Sent Events）。压测脚本每隔几秒建立一批连接，收几个 token 就主动断开——模拟真实用户「看到开头不感兴趣就划走」的行为。

按理说连接断了、请求结束，对应的 goroutine 应该一起消失。但 `go_goroutines` 这条线是这样的：

```text
压测开始     : 120
压测 10 分钟 : 480
压测 30 分钟 : 1,360
停止压测 1 小时: 1,340   ← 几乎不回落
```

内存曲线跟着一起抬。当时第一反应是「channel 忘了 close」，于是满仓找 `close(ch)`，结果发现该关的地方都关了。这就是这件事诡异的地方：**代码看起来没有任何资源泄漏的痕迹，但协程就是赖着不走。**

后来确认：问题不在「关没关 channel」，而在「取消信号只走了一半」。

## 背景：一个流式转发 handler 长什么样

先把现场抽象成一个最小模型。网关做三件事：

1. 接收客户端的 HTTP 请求；
2. 向上游大模型发起一个流式请求；
3. 把上游吐出来的数据块，一块一块写给客户端。

因为上游是流式的，handler 不能等全部返回再写，得一边收一边写。常规写法是起一个生产 goroutine 读上游、往 channel 里塞，handler 自己从 channel 里取、往 `ResponseWriter` 写。骨架大概是这样：

```go
func streamHandler(w http.ResponseWriter, r *http.Request) {
    flusher, ok := w.(http.Flusher)
    if !ok {
        http.Error(w, "streaming unsupported", http.StatusInternalServerError)
        return
    }
    w.Header().Set("Content-Type", "text/event-stream")
    w.Header().Set("Cache-Control", "no-cache")

    ch := make(chan string, 16)

    // 生产协程：读上游，塞进 channel
    go func() {
        defer close(ch)
        for chunk := range upstreamChunks(r.Context()) {
            ch <- chunk
        }
    }()

    // 消费：从 channel 取，写给客户端
    for chunk := range ch {
        fmt.Fprintf(w, "data: %s\n\n", chunk)
        flusher.Flush()
    }
}
```

这段代码能正常工作，正常到让人放松警惕。它有一个致命前提：**客户端会老老实实读到流结束。** 一旦客户端中途断开，前提就不成立了。

## 断链的那一刻：谁被取消了，谁没有被取消

Go 的 `net/http` 有一个很关键的行为：当客户端断开连接时，服务端这个请求对应的 `r.Context()` 会被自动取消。这是好事——意味着我们有了一个天然的取消信号。

问题在于，这个信号默认**只到达了持有 `r` 的那层**。

客户端断开后，发生的事情顺序是这样的：

```text
1. 客户端断开 TCP 连接
2. net/http 把 r.Context() 标记为 cancelled
3. handler 里的 fmt.Fprintf 下一次写入时返回 error（连接已断）
4. 但上面这段代码根本没检查写入的返回值！
5. for range ch 继续阻塞在「等下一块」
6. 生产协程继续 range upstreamChunks，并往 ch 里塞数据
7. ch 缓冲区（16）很快被填满
8. 生产协程阻塞在 ch <- chunk，永远醒不过来
```

第 4 步是第一个坑：`fmt.Fprintf` 和 `flusher.Flush()` 的返回值被丢弃了。更关键的是第 8 步——生产协程卡在 `ch <- chunk` 上时，它**手里没有 context**，它根本不知道客户端已经走了。它会一直等到有人来取 channel 里的数据，而那个人（handler）正在等 channel 的另一头。两个协程互相等，谁也不动。

这就是 goroutine 数只涨不落的真相：每一个「用户中途划走」的请求，都会永久留下一个生产协程。

## 最小复现：20 行代码把泄漏钉死

空谈无益，直接上一个能跑的最小复现。它不依赖任何上游服务，用定时器模拟流式数据：

```go
package main

import (
    "fmt"
    "net/http"
    "runtime"
    "time"
)

func streamHandler(w http.ResponseWriter, r *http.Request) {
    w.Header().Set("Content-Type", "text/event-stream")
    ch := make(chan string, 4) // 故意开小缓冲，加速复现

    go func() {
        defer close(ch)
        ticker := time.NewTicker(50 * time.Millisecond)
        defer ticker.Stop()
        for {
            select {
            case <-ticker.C:
                ch <- fmt.Sprintf("chunk-%d", time.Now().UnixNano())
            }
        }
    }()

    for chunk := range ch {
        if _, err := fmt.Fprintf(w, "data: %s\n\n", chunk); err != nil {
            // 客户端已断开 —— 但生产协程并不知道
            return
        }
        if f, ok := w.(http.Flusher); ok {
            f.Flush()
        }
    }
}

func main() {
    http.HandleFunc("/stream", streamHandler)
    go func() {
        for {
            time.Sleep(2 * time.Second)
            fmt.Println("goroutines =", runtime.NumGoroutine())
        }
    }()
    http.ListenAndServe(":8080", nil)
}
```

复现步骤：

```bash
# 终端 1：启动服务
go run main.go

# 终端 2：模拟客户端连上后立刻断开，重复 200 次
for i in $(seq 1 200); do
  curl -s --max-time 0.2 http://127.0.0.1:8080/stream > /dev/null
done
```

跑完再看终端 1 的输出，`goroutines` 会稳定停在一个远高于初始值的数字上，并且再也不降。那 200 个生产协程，全部卡在 `ch <-` 上。

注意这个复现里甚至没有真正的「上游」，泄漏来自最朴素的生产-消费结构。这说明问题具有普遍性——只要你的代码里存在「一个协程往 channel 写、另一个协程从 channel 读，而消费方可能提前退出」的结构，就中了招。

## pprof 现场：一眼看到卡在哪

线上不好用 `go run`，但可以开 pprof。加上这两行：

```go
import _ "net/http/pprof"

// 在 main 里
go func() {
    http.ListenAndServe(":6060", nil)
}()
```

然后抓 goroutine 的栈：

```bash
curl -s http://127.0.0.1:6060/debug/pprof/goroutine?debug=2 > goroutines.txt
```

在 dump 里数一下卡在 channel send 上的协程：

```bash
grep -c "chan send" goroutines.txt
```

如果输出是几十上百，基本可以确诊。随便挑一段栈出来看，形态几乎一模一样：

```text
goroutine 1841 [chan send, 8 minutes]:
main.streamHandler.func1()
    /path/to/main.go:24 +0x7a
created by main.streamHandler
    /path/to/main.go:20 +0x45
```

`[chan send, 8 minutes]` 这句话是决定性证据——一个协程在 channel 发送上卡了 8 分钟，而它本该在客户端断开的那一刻就退出。

> 顺带一提：如果怀疑是内存问题也可以抓 heap，但这个 case 里 heap 只会告诉你「对象很多」，goroutine dump 才能告诉你「卡在什么动作上」。排查并发泄漏，先抓 goroutine 再抓 heap，顺序别反了。

## 修法一：让生产协程也能看见 context

根因是生产协程没有取消信号。那把 `r.Context()` 传给它，并在发送时用 `select` 监听取消，就解决了：

```go
func streamHandler(w http.ResponseWriter, r *http.Request) {
    ctx := r.Context()
    ch := make(chan string, 4)

    go func() {
        defer close(ch)
        ticker := time.NewTicker(50 * time.Millisecond)
        defer ticker.Stop()
        for {
            select {
            case <-ctx.Done(): // 客户端断开 → 立刻收工
                return
            case <-ticker.C:
                select {
                case ch <- fmt.Sprintf("chunk-%d", time.Now().UnixNano()):
                case <-ctx.Done(): // 发送阻塞时也能被取消唤醒
                    return
                }
            }
        }
    }()

    for {
        select {
        case <-ctx.Done(): // handler 自己也要退出 for range
            return
        case chunk, ok := <-ch:
            if !ok {
                return
            }
            if _, err := fmt.Fprintf(w, "data: %s\n\n", chunk); err != nil {
                return
            }
            if f, ok := w.(http.Flusher); ok {
                f.Flush()
            }
        }
    }
}
```

这里有三个要点，缺一个都会留尾巴：

1. **生产协程的发送动作必须包在 `select` 里**，并且分支里有 `ctx.Done()`。只在外层循环 `select` 是不够的——协程大部分时间卡在发送那一行，根本回不到外层循环。
2. **消费端不能再用 `for range ch`**，因为生产协程取消后会 `close(ch)`，`for range` 虽然能自然结束，但你无法在等待下一块的同时响应取消。改成 `select` 显式监听 `ctx.Done()`。
3. **写入返回值必须检查**。一旦 `Fprintf` 报错，立刻返回，别假装客户端还在。

## 修法二：用 errgroup 把生命周期绑在一起

手写的 `select` 在简单场景够用，但真实网关往往有多条并发流（读上游、写心跳、写客户端），手工管理容易漏。这种时候用 `errgroup.WithContext` 更稳：

```go
func streamHandler(w http.ResponseWriter, r *http.Request) {
    g, ctx := errgroup.WithContext(r.Context())
    ch := make(chan string, 16)

    // 子任务一：读上游
    g.Go(func() error {
        defer close(ch)
        for {
            chunk, err := readUpstream(ctx) // 一个尊重 ctx 的读方法
            if err != nil {
                if errors.Is(err, context.Canceled) {
                    return nil // 取消不是错误
                }
                return err
            }
            if chunk == nil { // 流正常结束
                return nil
            }
            select {
            case ch <- *chunk:
            case <-ctx.Done():
                return ctx.Err()
            }
        }
    })

    // 子任务二：写客户端
    g.Go(func() error {
        for {
            select {
            case <-ctx.Done():
                return nil
            case chunk, ok := <-ch:
                if !ok {
                    return nil
                }
                if _, err := fmt.Fprintf(w, "data: %s\n\n", chunk); err != nil {
                    return err // 写失败会取消整个 group
                }
                w.(http.Flusher).Flush()
            }
        }
    })

    // 任何一个子任务出错，ctx 自动取消，另一个也会被带走
    _ = g.Wait()
}
```

`errgroup.WithContext` 的价值在于：任意一个 `g.Go` 返回非 nil 错误（或 panic），派生的 `ctx` 会自动取消，其余所有子任务都会收到信号。写客户端那个协程一旦 `Fprintf` 失败就返回错误，读上游的协程立刻跟着退出——不需要你手工在各个分支里传递取消。

不过要注意，`errgroup` 不是银弹。三个仍旧要盯的点：

- `readUpstream` 自己必须尊重 `ctx`。如果它内部用了不支持取消的 IO（比如某些老旧的 SDK），外面包得再好也没用，信号到它那儿就断了。
- `g.Wait()` 会等所有子任务返回。如果有协程没正确处理 `ctx.Done()`，`Wait` 会永远阻塞——这反而是个好事，测试时容易暴露问题。
- 别在子任务里再开「野生协程」（脱离 group 管理的 `go func`），否则又回到原点。

## 三个最常见的取消断链点

把这类问题归纳一下，取消信号失效基本就三个位置：

**断链点一：中间的 channel 发送。** 这是本文的主角。生产协程持有了数据，往 channel 送，但 channel 满了、消费方走了，它就在 `ch <-` 上原地卡死。修复：发送动作包 `select`，带上 `ctx.Done()`。

**断链点二：不看写入返回值。** HTTP 流式响应里，`Write`/`Flush` 的 error 是客户端状态的直接反馈。丢弃它，等于主动放弃了一个最早能发现断连的信号。修复：每次写都判错，出错即退出。

**断链点三：不响应 context 的下游调用。** 你把自己的 `ctx` 传给了数据库、HTTP 客户端、SDK，但对方内部根本没用它——比如用了 `http.Get` 而不是 `http.NewRequestWithContext`。修复：逐个审计下游调用，确认它们真的消费了 ctx。判断方法很简单：把 ctx 换成一个 1 毫秒后超时的 context，看调用会不会立刻返回。

## 一张能直接抄的排查清单

下次再遇到「协程/连接只涨不落」，按这个顺序走：

```text
1. 先抓 goroutine dump（debug=2），grep 状态码：
   - chan send 多 → 生产协程卡在发送（本文主角）
   - IO wait 多   → 下游调用不响应取消
   - select 多    → 在等一个永远不会来的信号
2. 看卡住协程的栈，定位到具体行号，确认它手里有没有 ctx。
3. 检查所有 channel 发送是否包了带 ctx.Done() 的 select。
4. 检查所有 Write/Flush 是否判了返回值。
5. 检查下游调用是否真正消费了传入的 ctx（用超时 context 验证）。
6. 修复后回到最小复现，确认 goroutine 数在客户端断开后能回落。
7. 补一条回归测试：客户端中途断开，断言协程数在 N 秒内回落。
```

第 7 条最容易被跳过，却是最值钱的。这类泄漏的回归测试不难写，核心是拿 `runtime.NumGoroutine()` 在断开前后各测一次，留一个宽松的阈值和等待窗口：

```go
func TestStreamCancelReleasesGoroutines(t *testing.T) {
    before := runtime.NumGoroutine()
    // 建立连接 → 收一块 → 主动断开，重复若干次
    for i := 0; i < 50; i++ {
        // ... 触发一次中途断开的流式请求
    }
    // 给取消传播留一点时间
    time.Sleep(500 * time.Millisecond)
    after := runtime.NumGoroutine()
    if after-before > 10 {
        t.Fatalf("goroutine leak: before=%d after=%d", before, after)
    }
}
```

阈值别卡太死（比如别写 `after > before`），因为测试框架自身、GC、网络库都可能产生波动。留一个稳定的余量，只抓「量大且持续」的真泄漏。

如果你们用的是 `go test -race`，还能顺带打开泄漏检测型的第三方库（比如 goleak）做更精确的断言——它按协程栈做过滤，能分辨「测试框架自己的常驻协程」和「你这次漏出来的」，比手工数 `NumGoroutine` 更不容易误报。但工具再好也替代不了本文第一节的复现思路：先让泄漏稳定发生，再谈用哪个工具抓。

## 一个容易被忽略的细节：缓冲区的大小会掩盖问题

最后补一个实操层面的观察。复现里我把 channel 缓冲开成 4，是为了让泄漏快速暴露。线上代码常见的是开一个较大的缓冲（比如 128 甚至 1024），这会让泄漏「看起来慢很多」——因为缓冲区要填满，生产协程才会卡死。

这其实是个陷阱。缓冲越大，从「客户端断开」到「生产协程真正卡住」之间的延迟越长，监控上的曲线就越平缓，越容易被当成正常的毛刺忽略掉。等它真正涨到报警阈值时，积累的泄漏协程已经不是几个，而是几百个。

所以我的建议是:**不要用「加大缓冲」来缓解这类问题，它只是把症状往后推。** 缓冲区该多大，由吞吐和背压需求决定；而取消信号的正确性，是由 `select` + `ctx.Done()` 决定的，两者是正交的。把取消传导做对之后，缓冲开多大都是安全的；做不对，开多大都只是时间问题。

## 写在最后

回到开头那张监控图。它看起来是内存问题，查下去是协程问题，再查下去是取消信号的问题，最后落到一个非常具体的代码行——`ch <- chunk` 没有 `select`。

这类 bug 的共同特征是：**在「一切正常」的路径上，代码完美工作；只有在「用户中途离开」这种异常路径上，才暴露出资源没回收。** 而流式网关恰恰是一个「异常路径是常态」的场景——用户划走、网络抖动、上游超时，每天都在发生。所以写流式代码时，默认假设会有人中途断开，把取消信号当成一等公民从头传到尾，比事后 pprof 排查便宜得多。

一句话收尾：在 Go 的并发代码里，**谁持有资源，谁就必须能看见取消信号**。中间任何一层「看不见」，泄漏就从那里开始。
