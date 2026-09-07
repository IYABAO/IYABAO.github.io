---
title: "Go pprof 实战：一个内存泄漏的定位全过程"
date: 2023-04-18T09:00:00+08:00
lastmod: 2023-04-18T09:00:00+08:00
draft: false
author: IYABAO
tags:
  - Go
  - pprof
  - 性能调优
categories:
  - 技术
summary: "服务内存每 6 小时涨 1G，重启就好了——典型的 goroutine 泄漏。用 pprof 火焰图、goroutine 栈、heap profile 一步步定位到根因，完整过程复盘。"
---

# Go pprof 实战：一个内存泄漏的定位全过程

线上服务有个诡异现象：内存每 6 小时涨 1G，重启后恢复，如此循环。第一反应是"哪里有缓存没清理"，实际定位完发现是 **goroutine 泄漏**——channel 没人收，goroutine 越积越多，每个都挂着内存。

这篇文章完整复盘 pprof 定位过程。

## 一、先打开 pprof 入口

```go
// 生产安全做法：独立端口 + 内网暴露
import _ "net/http/pprof"

go func() {
    // 注意：独立端口，不挂业务端口
    http.ListenAndServe("127.0.0.1:6060", nil)
}()
```

**生产不建议挂业务端口**，pprof 有安全风险（能看内存快照、能触发 GC），独立端口 + 防火墙限制访问。

## 二、第一轮：确认是不是 goroutine 泄漏

```bash
# 抓 goroutine 栈
curl http://127.0.0.1:6060/debug/pprof/goroutine?debug=1 > goroutine.txt
# 看 goroutine 总数
head -1 goroutine.txt   # goroutine profile: total 23014   ← 数量惊人！
```

**线索**：正常服务 goroutine 应该在几十到几百，2.3 万个必然泄漏。按栈聚合看是哪段代码：

```bash
# 统计每个栈点的 goroutine 数量
grep -A 5 "goroutine" goroutine.txt | sort | uniq -c | sort -rn | head -20
```

**发现**：大量 goroutine 卡在 `waiting on channel`——都是同一段代码创建后**永远在等 channel 消息**。

## 三、第二轮：heap profile 找内存大头

```bash
# 抓堆快照
curl "http://127.0.0.1:6060/debug/pprof/heap?debug=1" > heap.txt

# 或用 go tool 交互式分析
go tool pprof -http=:8081 http://127.0.0.1:6060/debug/pprof/heap
```

火焰图里看 `inuse_space`（当前占用）和 `alloc_space`（累计分配）：

- **inuse_space 大**：驻留内存多（真泄漏或大对象滞留）
- **alloc_space 大但 inuse 小**：高频临时分配（GC 压力）

**发现**：`inuse_space` 峰值集中在某结构体的 `[]byte` 字段，每个 64KB——和 goroutine 泄漏是同一处代码。

## 四、定位根因

```go
// 问题代码（简化版）
func processDeliveries(deliveries []Delivery) {
    results := make(chan Result, 100)   // 缓冲 100
    for _, d := range deliveries {
        go func(d Delivery) {
            r := processDelivery(d)
            results <- r      // 发送到 channel
        }(d)
    }
    // ❌ 只读了 100 条就 return 了！
    for i := 0; i < 100; i++ {
        result := <-results
        handleResult(result)
    }
}
```

**根因**：`deliveries` 有 1 万个，但主协程只消费 100 条就返回——剩下 9900 个 goroutine 在 `results <- r` 上永久阻塞（channel 满了，没人收）。每个 goroutine 挂着 `r`（含 64KB 的 HTML 内容），内存泄漏。

**两处错误**：
1. goroutine 数 = 任务数（1 万），没有并发上限
2. 消费逻辑不完整，channel 没人收

## 五、修复

```go
func processDeliveries(ctx context.Context, deliveries []Delivery) error {
    // 1. 并发上限：Worker Pool，而不是每任务一 goroutine
    workers := 20
    jobs := make(chan Delivery)
    results := make(chan Result, workers)

    var wg sync.WaitGroup
    for i := 0; i < workers; i++ {
        wg.Add(1)
        go func() {
            defer wg.Done()
            for d := range jobs {
                select {
                case results <- processDelivery(d):
                case <-ctx.Done():
                    return
                }
            }
        }()
    }

    go func() {
        defer close(jobs)
        for _, d := range deliveries {
            select {
            case jobs <- d:
            case <-ctx.Done():
                return
            }
        }
    }()

    // 2. 消费完所有结果再退出
    go func() {
        wg.Wait()
        close(results)
    }()
    for r := range results {
        handleResult(r)
    }
    return nil
}
```

**修复要点**：
1. **goroutine 有上限**（Worker Pool）
2. **消费完整**（`range results` 直到 close）
3. **ctx 兜底**：取消时 goroutine 能退出

## 六、验证

```bash
# 修复后观察
kubectl top pod delivery-service   # 内存平稳，不再阶梯式上涨

# 压测回归
go test -race ./...                 # race 检查
k6 run load.js                      # 压测 1 小时看内存曲线
```

**验收标准**：压测 2 小时，内存曲线平稳（涨跌随流量），不再单调递增。

## 七、预防清单

```
✅ goroutine 必须有退出路径（ctx 或 channel close）
✅ 批量任务用 Worker Pool，不裸开 goroutine
✅ channel 发送方考虑"没人收"的兜底（select + ctx）
✅ 上线前压测看内存曲线（单调递增 = 泄漏）
✅ pprof 独立端口 + 内网保护
```

## 总结

pprof 定位泄漏的套路：

1. **goroutine profile**：看总数 + 栈聚合，找"永远在等"的 goroutine
2. **heap profile**：inuse_space 找驻留大头，和 goroutine 栈交叉验证
3. **根因**：通常是"goroutine 没有退出路径"或"channel 无人消费"
4. **修复**：并发上限 + 完整消费 + ctx 兜底
5. **验证**：压测看内存曲线，`-race` 检查

**Go 服务的内存问题，一半是 goroutine 泄漏**。记住一句话：每个 `go func` 都要回答"它什么时候退出、谁保证它退出"。回答不了的，就是下一个 6 小时涨 1G 的定时炸弹。
