---
title: "升级到 Go 1.23 定时器就不泄漏了？真正开关是 go.mod 里那行版本号"
date: 2026-11-21T12:00:00+08:00
draft: false
tags: ["Go", "定时器", "内存泄漏", "GODEBUG", "踩坑记录"]
categories: ["技术复盘"]
description: "都说 Go 1.23 修好了 time.After 在循环里的定时器堆积，我把同一个程序在 1.23.4 编译器下换了两种 go.mod 版本指令来跑：200 万个定时器，内存增量一个是 0.02MB，一个是 508.69MB。编译器版本没变，变的只是 go.mod 里那行 go 指令。本文给出三组可复跑对照，说明这个开关到底是什么、为什么语言版本会管到运行时行为，以及 Stop/Reset 的老坑是不是真的消失了。"
---

> 本文所有数字来自本机 Go 1.23.4 的实跑输出，命令、数值、退出状态均为原文，可复跑。代码只用标准库，不含任何公司内部信息、账号或密钥。

## 一、一句被说漏了半截的结论

「Go 1.23 修好了 `time.After` 的内存泄漏，循环里可以随便用了。」

这句话我在技术群里看到至少三次，它半对半错。对的那半：Go 1.23 确实改了定时器实现，不再引用的定时器可以被垃圾回收，不必等到到点。错的那半：**这个改动不是由编译器版本决定的，而是由 `go.mod` 里的语言版本指令决定的。**

也就是说，你把工具链升到 1.23.4，只要 `go.mod` 还写着 `go 1.22`，旧行为原样保留。我一开始也不信，直到把同一个二进制换着版本跑了一遍，看到下面这组数字。

## 二、实验：200 万个一小时后才到点的定时器

实验逻辑很简单：循环创建 200 万个定时器，每个都设成一小时后触发，然后立刻丢掉引用。再强制 GC，量堆内存的净增量。

```go
package main

import (
	"fmt"
	"runtime"
	"time"
)

func heapAllocMB() float64 {
	runtime.GC()
	var m runtime.MemStats
	runtime.ReadMemStats(&m)
	return float64(m.HeapAlloc) / (1024 * 1024)
}

func main() {
	const n = 2_000_000
	before := heapAllocMB()
	for i := 0; i < n; i++ {
		_ = time.NewTimer(time.Hour) // 立即丢弃引用，1 小时后才到点
	}
	after := heapAllocMB()
	fmt.Printf("timers=%d before=%.2fMB after=%.2fMB delta=%.2fMB\n", n, before, after, after-before)
}
```

关键点在 `_ = time.NewTimer(time.Hour)`：定时器建出来就没人持有。旧实现里，这些定时器还挂在运行时的全局定时器堆上，GC 不敢回收，只能等一小时到点后才释放；新实现里它们可回收，GC 一轮就清掉。所以内存增量能直接反映语义差异。

## 三、三组对照：编译器没变，结果差了一万倍

同一个 `main.go`，同一个 1.23.4 编译器，只改 `go.mod` 的版本指令或 `GODEBUG` 环境变量。

第一组，`go.mod` 写 `go 1.23`，默认跑：

```text
===RUN main.go with go1.23 directive===
timers=2000000 before=0.26MB after=0.27MB delta=0.02MB
```

第二组，`go.mod` 改成 `go 1.22`，编译器还是 1.23.4：

```text
===RUN main.go with go1.22 directive under 1.23.4 compiler===
timers=2000000 before=0.25MB after=508.95MB delta=508.69MB
```

第三组，`go.mod` 保持 `go 1.23`，但用 `GODEBUG=asynctimerchan=1` 强制回到旧的异步通道行为：

```text
===LEGACY asynctimerchan=1===
timers=2000000 before=0.25MB after=509.88MB delta=509.62MB
```

三组放一起看：

| 版本指令 | GODEBUG | 内存增量 |
| --- | --- | --- |
| go 1.23 | 默认 | 0.02 MB |
| go 1.22 | 默认 | 508.69 MB |
| go 1.23 | asynctimerchan=1 | 509.62 MB |

`go 1.22` 那组是最容易被忽略的：编译器是新的，代码是新的，行为却是旧的。原因就是那行 `go` 指令。

## 四、为什么语言版本会管到运行时行为

Go 团队有一条兼容承诺：把 `go.mod` 的 `go` 版本升上去，程序行为可以按新版本变；但只要版本指令停在旧的，即便用再新的编译器构建，程序也应该表现得像旧版本。这条承诺不只管语法，也管那些「能观测到的行为变化」——定时器 GC 语义正属于这一类。

所以 Go 1.23 把新语义绑定在 `go 1.23` 这个语言版本上，而不是绑定在编译器上。做不到这一点的改动，会直接破坏大量存量服务的隐性假设。运行时需要一个开关来区分「这是老程序」还是「这是声明了新版本的程序」，`go.mod` 里的版本指令就是这个开关。

`GODEBUG=asynctimerchan=1` 则是另一条退路：它让那些已经声明了 `go 1.23`、但因为某个依赖库依赖旧语义而临时出问题的项目，可以在不动代码的情况下紧急回退。它是应急旋钮，不是常态配置。

换句话说，两个开关层次不同：

- **go.mod 版本指令**：决定你这个模块「声明」用哪套语义，是长期决定；
- **GODEBUG**：对单个进程做运行时覆盖，是短期救火。

升级工具链不等于升级语义。要真正拿到新行为，得把 `go.mod` 的 `go` 指令一起升上去。

## 五、那 Stop / Reset 的老坑消失了吗

很多人顺带以为：定时器能 GC 了，那些关于 `Stop()` 要排空通道的老规矩也不用记了。不。GC 语义和通道里残留的旧值，是两件事。

看经典的「复用一个 Timer」场景：定时器触发一次后，通道里留着一个旧值，调用 `Reset` 继续用。老教程会让你写 `if !t.Stop() { <-t.C }` 去排空；但在某些时序下，这个排空读会永久阻塞——因为值已经被 `select` 读走了，通道是空的。

我写了最小用例实测：定时器触发一次、读走超时值，然后直接 `Reset`，再等第二次触发。

```go
package main

import (
	"fmt"
	"time"
)

func main() {
	t := time.NewTimer(20 * time.Millisecond)

	<-t.C // select 已经消费了这次超时值
	fmt.Println("fired at:", time.Now().Format("15:04:05.000"))

	// 这里若再写 <-t.C 排空就会阻塞；通道已被读走，直接 Reset
	t.Reset(20 * time.Millisecond)

	start := time.Now()
	select {
	case <-t.C:
		fmt.Println("second fire after:", time.Since(start).Milliseconds(), "ms")
	case <-time.After(time.Second):
		fmt.Println("BLOCKED: stale drain would hang here")
	}
}
```

实跑输出：

```text
fired at: 12:11:08.875
second fire after: 20 ms
```

直接 `Reset` 正常触发第二次，20 毫秒，没有阻塞。结论是：Go 1.23 让无引用定时器可回收，但**通道残留值导致的排空阻塞跟 GC 无关**，该避开的错误写法还是要避开。别把两个坑混为一谈，也别因为一个被填了就以为另一个也没了。

## 六、落地建议

把这次实验收敛成三条能直接用的规矩：

**第一，升级 Go 工具链后，单独确认 `go.mod` 的 `go` 指令。** `go version` 只告诉你编译器版本，不告诉你模块用哪套语义。两件事分开看。想拿到定时器新语义，就明确把 `go.mod` 升到 `go 1.23`。

**第二，把 Go 1.23 的定时器改动记成「语言版本特性」，不是「编译器版本特性」。** 写进团队升级文档时，别写「升级到 1.23 就好了」，要写「`go.mod` 升到 1.23 后，无引用定时器可回收」。差这一句，就会有人升了工具链却一直在旧语义上跑。

**第三，遇到可疑的定时器堆积，先用 `GODEBUG` 做二分。** 同一个进程加不加 `asynctimerchan=1`，内存差出几百 MB，就能一眼确认是不是踩在旧语义上。这比翻代码猜快得多。

## 七、复现附录

环境确认：

```powershell
go version
```

三组实验的命令序列（`main.go` 见第二节，`go.mod` 分别写 `go 1.23` 与 `go 1.22`）：

```powershell
# 第一组：go 1.23 默认
go run main.go

# 第二组：把 go.mod 的 go 指令改成 1.22，编译器不变
go run main.go

# 第三组：go 1.23 + 旧异步通道语义
$env:GODEBUG = "asynctimerchan=1"
go run main.go
Remove-Item Env:GODEBUG
```

排空实验：

```powershell
go run drain.go
```

本文的价值不在于「Go 1.23 修好了泄漏」这条结论本身，而在于把它的适用边界钉死：**编译器版本只是入场券，真正决定你拿到哪套语义的，是 `go.mod` 里那行不起眼的版本号。** 升级这种事，差一行配置，结果就差一万倍。
