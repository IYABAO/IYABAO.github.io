---
title: "自检脚本会撒谎：从 Markdown 复制到 UTF-8 解码的三个假信号"
date: 2026-11-20T10:00:00+08:00
draft: false
tags: ["PowerShell", "正则", "UTF-8", "工程治理", "踩坑记录"]
categories: ["技术复盘"]
description: "一条正则从文档表格复制进命令行，竖线从「或」变成字面字符；Invoke-WebRequest 拿到 62 字节却说中文关键词不存在；字符数 18 被当成字节数上报。三个假信号让「全绿」的自检彻底失真，全部有本机可复现输出。"
---

> 本文所有数字都是今天在一台 Windows 机器上现场跑出来的，命令附在文末，可原样复跑。涉及的账号、内网地址、项目路径与人名均已泛化；文中不出现任何真实公司、客户或同事信息。写这篇的动机很单纯：我那条"全绿"的自检脚本，骗了我一整晚。

## 一、起点：一条"全绿"的自检，结果是个假阳性

我手头有一段日常自检：从落盘的命令清单里取出复算命令，跑一遍，看关键词命中没有、看 exit code 是不是 0、看产物字节数够不够。三条都绿，就算过关。

那天三条全绿，我以为稳了。第二天复核，发现其中一个"命中"根本是假的——脚本说关键词在页面里，实际上页面里压根没有；另一个"未命中"也是假的——关键词明明在，脚本说不在。

问题不在被测对象，在**自检脚本自己**。它会在三种情况下安静地给出错误结论，而且不报任何错、exit code 全是 0。这才是最阴的地方：一个会崩的脚本不可怕，一个"绿得理直气壮"却结论错误的脚本才可怕。

下面三个坑，都是我从这次事故里逆向出来的，每一个都有可复现的最小实验。

## 二、假信号一：从 Markdown 复制的正则，竖线从"或"变成"字面字符"

第一条失真发生在命令的搬运过程。

技术文档里的复算命令，我习惯写成 Markdown 表格，一列"用途"一列"命令"。问题就出在表格上：Markdown 表格用 `|` 当列分隔符，命令里如果本身有正则的"或"运算符 `|`，写文档的人（也就是我）会下意识地转义成 `\|`，免得表格被切断。渲染出来看着是正常的 `|`，复制到命令行时，某些编辑器/终端把转义一起带了出来，于是命令行里变成：

```powershell
$pattern = 'alpha\|beta'
```

在 .NET / PowerShell 正则里，`\|` 不是"或"，而是**转义的字面竖线字符**。也就是说，这条正则匹配的是字符串 `alpha|beta`（中间真有一个竖线），而不是"alpha 或者 beta"。语义整个反了。

我用一个最小实验钉死它。同一段文本 `x alpha y`，跑两条正则：

```powershell
$txt = 'alpha|beta'
$pat_good = 'alpha|beta'
$pat_bad  = 'alpha\|beta'
Write-Output ("GOOD on 'alpha|beta' = " + ($txt -match $pat_good))
Write-Output ("BAD  on 'alpha|beta' = " + ($txt -match $pat_bad))
$line = 'x alpha y'
Write-Output ("GOOD on 'x alpha y' = " + ($line -match $pat_good))
Write-Output ("BAD  on 'x alpha y' = " + ($line -match $pat_bad))
```

实测输出：

```text
GOOD on 'alpha|beta' = True
BAD  on 'alpha|beta' = True
GOOD on 'x alpha y' = True
BAD  on 'x alpha y' = False
```

关键看最后两行：文本 `x alpha y` 里明明有 `alpha`，正确的"或"正则 `alpha|beta` 命中了（True），而带转义的 `alpha\|beta` 没命中（False）。**这就是假阴性：该报"命中"的地方报了"没命中"。**

反过来更危险的场景：如果你的自检是"用这条正则去扫，命中就算证据齐"，那么被污染的正则可能在一个恰好含竖线的文本上命中，让你以为证据在，实际是撞上了字面竖线——假阳性。两种方向都能中招。

**修法：** 写复算命令时不要让 `|` 直接出现在 Markdown 表格单元格里，用行内代码块包起来并在表格外用独立代码块给完整命令；正则的"或"如果一定要写进表格，用字符类 `[|]` 或把命令整体放进 fenced code block，复制前肉眼确认没有多余的 `\`。更稳的做法是给正则配一个**反例探针**：拿一条"按理不该命中"的文本先跑一次，确认它真的不命中，再拿"按理该命中"的文本跑一次，两次都符合预期才信这条正则。

## 三、假信号二：Invoke-WebRequest 拿到字节，却说中文关键词不存在

第二条失真在 HTTP 验收环节。

我用 PowerShell 的 `Invoke-WebRequest` 检查一个线上页面里有没有某个中文关键词，写法很自然：

```powershell
$r = Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:18765/'
$r.Content.Contains('中文解码探针')
```

结果是 `False`。按这个结论，页面里没有这个词。但我用 curl 把同一 URL 落地成字节，再按 UTF-8 显式解码，同样的 `.Contains()` 却返回 `True`。

为了把根因钉死，我起了一个本地临时 HTTP 服务，返回一段固定 HTML（含中文"中文解码探针"），**响应头故意只写 `Content-Type: text/html`，不声明 charset**，然后两种读法对照：

```powershell
$r = Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:18765/'
Write-Output ("IWR RawContentLength = " + $r.RawContentLength)
Write-Output ("IWR .Content.Contains('中文解码探针') = " + $r.Content.Contains('中文解码探针'))
$tmp = Join-Path $env:TEMP 'iwr_curl_probe_20261120.html'
curl.exe -s 'http://127.0.0.1:18765/' -o $tmp
$bytes = [IO.File]::ReadAllBytes($tmp)
$text  = [Text.Encoding]::UTF8.GetString($bytes)
Write-Output ("curl bytes = " + $bytes.Length)
Write-Output ("curl UTF8.Contains('中文解码探针') = " + $text.Contains('中文解码探针'))
```

实测输出：

```text
IWR RawContentLength = 62
IWR .Content.Contains('中文解码探针') = False
curl bytes = 62
curl UTF8.Contains('中文解码探针') = True
```

这四行的信息量很大：

1. `RawContentLength = 62`、`curl bytes = 62`——两种读法拿到的**字节数完全一致**，说明网络层没问题，页面确实取到了、而且取全了。
2. IWR 的 `.Contains()` 是 `False`，curl+UTF-8 是 `True`——差异只可能出在**字节到字符串的解码环节**。

根因：响应头没声明 charset 时，Windows PowerShell 5.1 的 `Invoke-WebRequest` 会按它自己的默认编码（在旧行为里是 Latin-1 / 系统区域码，而不是 UTF-8）去解读这 62 个字节，中文被解成乱码，`.Contains('中文解码探针')` 自然匹配不上。**字节没错，解码错了。**

**修法：** 凡是"验收页面里有没有某个中文关键词"这类检查，别信 IWR 的 `.Content.Contains()` 这种一行断言。用 curl（或 `Invoke-WebRequest -OutFile`）把响应落成字节文件，再用 `[Text.Encoding]::UTF8.GetString([IO.File]::ReadAllBytes($path))` 显式按 UTF-8 解码后断言。状态码和字节数可以用 IWR/curl 直接取——这两个字段不受中文解码影响——但**文本内容判断必须走"落地字节 + 显式解码"这条路**。

顺带说一句，PS 5.1 里 IWR 的 `.Content.Contains(中文)` 假阴性，和我之前踩过的另一个坑是同源的：只要中间有一次"按默认编码猜"，中文就可能悄悄失真。把它当成一条铁律记下来：**文本断言不落地字节不算数。**

## 四、假信号三：字符数冒充字节数，大小自检直接缩水

第三条失真最隐蔽，因为它看起来只是个"单位问题"。

我在自检里判断"产物写够了没有"，一开始用的是写文件工具的回显值。那个数字是**字符数**。我拿它当**字节数**上报，一直没觉得不对，直到某次拿磁盘实测一对：

```powershell
$s = '中文编码探针-OK-20261120'
'chars=' + $s.Length
'utf8bytes=' + ([Text.Encoding]::UTF8.GetByteCount($s))
```

实测输出：

```text
chars=18
utf8bytes=30
```

18 个字符，UTF-8 下 30 个字节。一个中文字符占 3 字节，所以只要稿件里有中文，字符数就会比字节数**少一大截**——我这篇稿子中文密集，两者能差出一倍以上。

后果很直接：如果自检门槛写的是"产物 ≥ 4000 字节"，而我用字符数 2500 去比，会误判成不达标（假阴性）；反过来若门槛是"≤ 某个上限"，字符数又会让你以为没超（假阳性）。两种误判都能让自检给出错误结论，而且数字看起来还挺像那么回事。

**修法：** 报文件大小、比大小门槛，一律用磁盘实测字节数：

```powershell
Get-Item -LiteralPath '<产物绝对路径>' | Select-Object Name, Length, LastWriteTime
```

写文件工具的回显、编辑器的"字数统计"、`.Length`（字符串）——这些都是字符数或字数，不是磁盘字节，不能拿来当字节数用。**字节数只有磁盘说了算。**

## 五、加演：一条"过期经验"差点让我误判

三个假信号查完，我顺手验了一条一直深信不疑的旧经验：*"PowerShell 5.1 读 UTF-8 无 BOM 的 .ps1 会按 ANSI 解码，中文字符串全乱码，脚本直接报错。"*

这条经验我吃过亏，一直当常识。但今天在本机一测，结论不成立了。先看环境：

```powershell
$PSVersionTable.PSVersion.ToString()
'ANSIcodepage=' + [Text.Encoding]::Default.CodePage
```

实测输出：

```text
5.1.26100.9818
ANSIcodepage=65001
```

65001 就是 UTF-8。这台机器把系统区域设成了"全局 UTF-8"（Beta 版选项里那个 Use Unicode UTF-8 for worldwide language support），于是 PS 5.1 的默认编码也跟着变成 UTF-8。我把同一段中文脚本分别存成无 BOM 和有 BOM 两份，都用 `powershell -File` 跑：

```text
NO_BOM rc=0 stdout='中文编码探针-OK-20261120' stderr=''
BOM    rc=0 stdout='中文编码探针-OK-20261120' stderr=''
```

两份都 rc=0、输出正常。**旧经验在这台机器上失效了。**

这件事的教训比前三个坑更值钱：经验是有前提条件的。脱离了"ANSI codepage 不是 65001"这个前提，"无 BOM 必乱码"就是一条会骗人的旧结论。所以现在但凡要把一条"以前是这样的"写进自检依据，我都先跑一遍最小实验确认它在当前环境还成立——**经验要用实测续期，不能无限期赊账。**

## 六、把自检从"会撒谎"改造成"可信"的三条规矩

三个假信号加一条过期经验，表面是四个技术坑，根子是同一个：**自检本身没有被检验过。** 一个从来不给出反例的检查器，你无法知道它是不是真的在工作。

我把改造原则收敛成三条：

**规矩一：每条正则断言都要配反例探针。** 先拿一条"按理不该命中"的文本跑，确认它不命中；再拿"按理该命中"的跑，确认命中。两头都对，才信这条正则。这样第二节的 `\|` 污染当场就会暴露——反例文本上它本该 False 却……正好，正反对照一跑就露馅。

**规矩二：文本断言必须"落地字节 + 显式解码"。** 页面里有没有某个词、响应里有没有某段内容，一律 curl 落地成字节文件再按 UTF-8 解码后判断。状态码、字节数这类不受编码影响的字段，可以直接取，但也建议同时记录字节数，作为"内容确实取全了"的旁证——第三节的对照里，正是 62=62 让我把问题锁定在解码而不是网络。

**规矩三：数字口径统一到磁盘。** 字节数用 `Get-Item`，不用字符数、不用回显、不用字数统计。每一次上报都问自己一句："这个数字是磁盘量出来的，还是某个工具换算给我的？"

还有第四条，是关于人的：**把旧结论当假设，不当公理。** 环境会变（codepage 会改、工具版本会升、站点会加 charset），昨天成立的今天未必成立。花三十秒跑个最小实验，比基于旧经验排查两小时便宜得多。

## 七、复现附录

下面三段可以直接在 PowerShell 里跑，用来复核本文三个假信号。均为本地实验，不碰任何外部服务。

假信号一（正则竖线），见第二节代码块；核心是对比 `alpha|beta` 与 `alpha\|beta` 在文本 `x alpha y` 上的命中差异。

假信号二（IWR 中文假阴性），需要一个返回无 charset 的 UTF-8 HTML 的本地服务，第三节给了对照代码：起服务用 Python 标准库 `http.server` 即可，关键是响应头只给 `Content-Type: text/html`。

假信号三（字符数冒充字节数）：

```powershell
$s = '中文编码探针-OK-20261120'
'chars=' + $s.Length
'utf8bytes=' + ([Text.Encoding]::UTF8.GetByteCount($s))
```

环境确认（解释第五节为何旧经验失效）：

```powershell
$PSVersionTable.PSVersion.ToString()
'ANSIcodepage=' + [Text.Encoding]::Default.CodePage
```

写完这篇，我把那条"全绿"的自检脚本按上面三条规矩重写了一遍。它现在会故意在开头跑两个反例探针，任何一个不符合预期就 red——我宁可它多报几次警，也不想再被一个笑眯眯的"全绿"骗一整晚。自检的价值不在于它多常说"通过"，而在于它该说"不通过"的时候，真的会说。
