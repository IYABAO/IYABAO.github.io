---
title: "巡检系统为什么会自己咬自己——一次 C5 修复引发的 3-BOM 自伤"
date: 2026-11-21T19:40:00+08:00
draft: false
tags: ["自动化运维", "故障复盘", "编码规范", "护栏设计", "PowerShell"]
categories: ["工程实践"]
description: "为了让失败不再被掩盖，我改了巡检判据的口径。改完当场，自己上一轮遗留的四个无 BOM 中文 helper 把编码检查段打红，有效覆盖从 10 掉到 8、盲段从 1 涨到 3，卡面数字因此过期两格。这篇复盘讲护栏怎么变成故障源，以及为什么新增 helper 必须先过 BOM/哈希自检再落 scripts。"
---

> 说明：本文来自我自己一套本地多 agent 运维实践的真实事故。命令、字段、退出码、字节数都是真实结构与实测值。为保护隐私，agent 一律写作 X（判方/独立复算方）与 C（执行修复方），工作目录写作 `<workdir>`，任务 id、主机名、端口、账号等已泛化；文中哈希前 16 位只是改造留证的校验指纹。每个关键数字后标注了它的原始来源文件（抽象路径），便于逐条核对。

## 一、现象：卡面数字一夜过期两格

这套系统里有一条判据叫 C5，口径是「有效自动检查段数」。它有三个数经常一起出现：

- **目标**：源码里声明的检查段数，固定是 11；
- **当前值**：最近一次可复算巡检的有效覆盖读数；
- **盲段数（blind）**：本轮判 FAIL/BROKEN 的去重段号数。

当天傍晚，卡面 C5 行的当前值连着变了两次：先是 `11 → 10`，一个多小时后又从 `10 → 8`。两格过期看起来像「卡面又算错了」，但逐条查下来，两次变化性质完全不同——第一次是我**主动**把口径改诚实了，第二次是**我自己造的故障**把读数打了下来。

事后把两次变化的来源钉死（来源：`<workdir>/reports/ops/C5_FAIL_VISIBILITY_FIX_20261121.md`、`<workdir>/reports/ops/C5_WRAPUP_20261121.md`）：

| 时点 | 当前值 | blind | 性质 |
|---|---|---|---|
| 口径修正完成（18:1x） | 10 | 1 | 主动改口径：FAIL 段不再计入有效覆盖 |
| 判方独立实跑（19:04） | 8 | 3 | 自伤在场：四个无 BOM helper 把 3-BOM 打红 |
| 修复后实跑（19:1x） | 9（实测）／8（卡面定格） | 2 | 自伤消除，blind 掉一段 |

一眼能看出的异常：blind 从 1 涨到 3，多出来的两段里有一段是**编码检查（3-BOM）**，而触发它的不是别人，正是几个小时前我为修 C5 而写的 helper 脚本。这就是标题里「自己咬自己」的由来。

## 二、先修的那个洞：失败被掩盖

要理解自伤，得先知道我那天在修什么。

C5 的运行时汇总区里，有一段代码负责把本轮巡检的各段状态汇总成一个「有效覆盖段数」。原来的口径有个很隐蔽的缺陷：**段号去重时，FAIL 段和 PASS 段一视同仁**——只要某段号出现过，就算覆盖到了。

用真实日志复现一下这个洞（来源：`<workdir>/reports/ops/C5_FAIL_VISIBILITY_FIX_20261121.md` §2.1）：判据 12 下面有四个子段，`12-VERIFY` 判 FAIL，但 `12-PHASE`、`12-DVD`、`12-DECLH` 三个子段都判 PASS。旧口径先按段号去重，段号 12 被那三个 PASS 提前占进集合，FAIL 就被中和掉了——于是 `12-VERIFY` 明明失败，C5 仍然报 11。

```powershell
# 旧口径（节选）：只剔 SKIP，FAIL/BROKEN 与 PASS 同等计入段号去重
foreach ($r in $rows) {
    if ($r.Status -eq 'SKIP') { continue }
    $c5Nums[$r.SegNum] = 1        # 12-VERIFY FAIL 也被这段号计进去了
}
$c5eff = $c5Nums.Count            # 于是 FAIL 被同段 PASS 掩盖
```

这种「段 FAIL 时判据仍然达标」的状态，就是所谓的**失败被掩盖**。它比「判据红了」危险得多：判据红了会有人去看，判据绿着但底下有 FAIL，没人会去看。

## 三、口径怎么改：只数 PASS，FAIL 单列 blind

修法是把三件事拆成三个数：

- **real**：段号去重后，本轮真正判过且**通过**的有效覆盖段数（等于 C5_EFFECTIVE）；
- **blind**：本轮出现 FAIL/BROKEN 的去重段号数——失败不再被去重中和，单独点名；
- **decor**：段 9（informational，只输出观察事件不判 FAIL）与无数字段（自证、看门狗类）。

关键规则是「**一段内 FAIL 不能被同段 PASS 吞掉**」：只要某段号出现任一 FAIL/BROKEN，该段号整段归 blind，并从 real 集合中移除。

```powershell
# 新口径（节选）：FAIL/BROKEN 归 blind，并从 real 剔除
$c5RealNums = @{}; $c5BlindNums = @{}; $c5DecorNums = @{}
foreach ($r in $rows) {
    $n = $r.SegNum
    if ($r.Status -eq 'FAIL' -or $r.Status -eq 'BROKEN') { $c5BlindNums[$n] = 1 }
    else { if (-not $c5BlindNums.ContainsKey($n)) { $c5RealNums[$n] = 1 } }
}
foreach ($bn in $c5BlindNums.Keys) { [void]$c5RealNums.Remove([int]$bn) }
$c5eff = $c5RealNums.Count
$c5Blind = $c5BlindNums.Count
Write-Host ("RESULT: C5_VISIBILITY = real={0}/blind={1}/decor={2}" -f $c5eff, $c5Blind, $c5Decor)
```

用夹具自检验证新口径（注入「段 3 PASS + 段 9 PASS + 12-VERIFY FAIL + 12-PHASE/DVD/DECLH PASS + 看门狗 PASS」），输出 `real=1/blind=1/decor=2`——段号 12 被正确剥离出 real，段 9 与无数字段归 decor。

真实日志 A/B 实跑证明改前 11、改后 10，差值唯一来自段号 12 的 `12-VERIFY` FAIL。卡面当前值同步从 11 改到 10，注明口径修正，**目标 11 一字未动**。到此为止，这是一次干净的修复。

## 四、自伤发生：四个 helper 把 3-BOM 打红

问题出在修复过程本身。

为了做上面的 A/B 实跑和卡面复算，我临时写了 5 个「复算/自检 helper（一次性，非交付物）」。其中 4 个落进了生产扫描目录 `<workdir>/scripts` 根下。它们是我在 18:13–18:15 用**无 BOM** 方式落盘的中文脚本（来源：`<workdir>/reports/ops/C5_WRAPUP_20261121.md` §1.1）：

```text
_c5_ab_20261121.ps1            | 3584 B | NOBOM | nonascii=624
_c5_card_20261121.ps1          |  623 B | NOBOM | nonascii=104
_c5_src_20261121.ps1           | 2975 B | NOBOM | nonascii=153
_c5_verify_20261121.ps1        | 2131 B | NOBOM | nonascii=144
```

而巡检的第 3 段（3-BOM）干的事，正是递归扫三家 `scripts` 目录，把「无 BOM 且含非 ASCII 字节」判为 HIGH-RISK。于是 19:04 判方独立实跑时，原文点名了这 4 个文件：

```text
3-BOM   FAIL  high=4  high-files=<workdir>/scripts/_c5_ab_20261121.ps1;
<workdir>/scripts/_c5_card_20261121.ps1;
<workdir>/scripts/_c5_src_20261121.ps1;
<workdir>/scripts/_c5_verify_20261121.ps1  => FAIL
PATROL RESULT: 12 PASS / 4 FAIL / 0 SKIP | C5_EFFECTIVE = 8
RESULT: C5_EFFECTIVE = 8
RESULT: C5_VISIBILITY = real=8/blind=3/decor=3
```

因果链非常直接：**我为了修「失败被掩盖」而造的临时脚本，自己构成了新的编码违规，把编码检查段打红**。blind 由 1 涨到 3，real 由 10 掉到 8，卡面当前值跟着过期到 8。

## 五、为什么无 BOM 中文脚本会「打红」一段

这不是吹毛求疵，是 Windows PowerShell 5.1 的真实坑。

同一份 `.ps1`，如果存成 UTF-8 无 BOM 且正文含中文，5.1 会按系统 ANSI（GBK）解码——中文注释和字符串变乱码，加载时直接抛 `ParserError`。所以本家的硬编码纪律是「`.ps1` 必须 UTF-8 带 BOM」。巡检段 3-BOM 就是这条纪律的 automated 版本：它不靠人自觉，而是把违规扫出来、判 FAIL。

这里有个值得记住的机巧：**护栏本身是被同一套纪律约束的**。我以为自己写的是「一次性 helper，非交付物」，但它落在了生产扫描目录里，对巡检来说它就是被扫对象——护栏不认「临时」这个标签。临时脚本不是免死金牌，落在 `scripts` 里就得遵守 `scripts` 的规矩。

## 六、blind 1→3、有效段 10→8 的逐段归因

为什么偏偏是这两个数？因为 C5 的三数口径里藏着一个恒等式。

源码段集恒定 11 段（段号 `0,1,2,3,4,6,8,11,12,14,15`），所以恒有：

```text
real + blind = 11        （decor 另计，不进这条等式）
```

blind 不是静态量，而是**本轮巡检里判 FAIL 的去重段号数**。三轮对照（来源：`<workdir>/reports/ops/C5_WRAPUP_20261121.md` §3.2）：

| 轮次 | 本轮 FAIL 段 | 进 blind 的段号 | real | blind | C5_EFFECTIVE |
|---|---|---|---|---|---|
| 18:1x 口径修正轮 | 仅 `12-VERIFY` | {12} | 10 | 1 | 10 |
| 19:04 判方实跑（自伤在场） | `0-EDITCHK` + `3-BOM` + `12-VERIFY` | {0, 3, 12} | 8 | 3 | 8 |
| 19:1x 修复后实跑 | `0-EDITCHK` + `12-VERIFY`（3-BOM 已 PASS） | {0, 12} | 9 | 2 | 9 |

`9-AUDIT` 那轮也 FAIL，但它是 informational、归 decor，**始终不进 blind**，所以不影响等式。18:1x → 19:04 之间新增两段 FAIL：`0-EDITCHK`（改脚本后没走 attestation 的正常归因漂移）和 `3-BOM`（本报告的自伤）。blind 从 {12} 变成 {0,3,12}，就是 `1→3`；real 从 11−1=10 变成 11−3=8，就是 `10→8`。

**卡面 11→10→8 的三次变化也能逐条对上**：11 是口径修正前的旧读数（失败被掩盖）；10 是口径修正后、只有一段 FAIL 时的诚实读数；8 是自伤把盲段推到 3 后的读数。三次都是同一条等式在不同运行期 FAIL 集合下的取值，不是三套算法。

## 七、卡面写 8、修复后实测是 9，是不是又错了

不是，这一点最容易误读，单独讲清楚。

修复 3-BOM 后，盲段少一段、real 多一段，数学上必然 `8 → 9`。但卡面当前值定格在 8，没有追改成 9，理由有三条（来源：`<workdir>/reports/ops/C5_WRAPUP_20261121.md` §4.4）：

1. **卡面锚定判方 19:04 的独立实跑轮**。Issue 给的归真基准就是 `C5_EFFECTIVE=8 / real=8/blind=3/decor=3`，定格 8 是本轮目标，不是笔误。
2. **追改成 9 才是真的错**。那等于把一个随运行期 FAIL 数漂移的量当成静态量钉死——下一轮 `0-EDITCHK` 或 `9-AUDIT` 状态一变又会漂，卡面永远追不上。
3. **目标 11 和源码段集 11 段自始至终没动**。复算源码段头仍是 `RESULT: C5 = 11`，反证了这一点。

一句话：**卡面当前值是「最近一次可复算巡检的有效覆盖读数」，不是源码属性**。blind 是运行期量，随当日 FAIL 段数漂移，这是设计如此，不是故障。把这个讲清楚，是为了杜绝下一轮再把它误读成「卡面又错了」然后去乱改。

## 八、修复：补 BOM，而不是把问题文件挪走

任务给了两条路：给 4 个 helper 补 UTF-8 BOM，或把它们迁进巡检已排除的 `_archive`。我选补 BOM，理由三条：

1. **直接消除违规本身**。`.ps1` 带 BOM 是本家硬纪律，补完这 4 个文件自身合规，既清掉 3-BOM FAIL，也让它们在 5.1 下可被正确加载。迁走只是「眼不见心不净」，问题文件仍然存在。
2. **不破坏历史证据的路径引用**。两轮报告都按 `<workdir>/scripts/_c5_*.ps1` 记录来源，迁移会让已落盘的路径失效，还得改写 README 和历史报告，牵连面更大。
3. **改动最小、可回滚**。仅 4 个文件各加 3 字节 BOM 头，逐份留 `.bak`，不动任何生产判据。

修复动作是「严格 UTF-8 解码验证 → 备份 → 写回带 BOM → 回读 → PSParser 解析」，逐文件输出（来源同上 §1.3）：

```text
_c5_ab_20261121.ps1     validUTF8=True  BOM=True  bytes=3584->3587  parseErr=0
_c5_card_20261121.ps1   validUTF8=True  BOM=True  bytes= 623-> 626  parseErr=0
_c5_src_20261121.ps1    validUTF8=True  BOM=True  bytes=2975->2978  parseErr=0
_c5_verify_20261121.ps1 validUTF8=True  BOM=True  bytes=2131->2134  parseErr=0
```

补完独立复扫，4 个目标文件由 HIGH-RISK 变 OK；巡检段 3-BOM 回到 PASS：

```text
[3-BOM] PASS  high-risk=0  (scanned=235, noBomAscii=58 advisory-only)
PATROL RESULT: 13 PASS / 3 FAIL / 0 SKIP | C5_EFFECTIVE = 9
RESULT: C5_VISIBILITY = real=9/blind=2/decor=3
```

## 九、可执行结论：新增 helper 先过 BOM/哈希自检再落 scripts

这次事故的根因不是「BOM 知识不足」——纪律早就写在文档里。根因是**落盘动作没有门禁**：写 helper 时脑子里想的是「临时脚本」，手上却直接写进了生产扫描目录，纪律靠人自觉就一定会漏。

所以结论不是一句「以后注意」，而是一道可执行的门禁：**任何新增 helper，先过 BOM/哈希自检，通过后才允许落进 `scripts`**。下面这段脚本可以直接放在落盘前置流程里，失败即 exit 非 0，拦住违规文件：

```powershell
# preland_helper_check.ps1 —— 新增 helper 落 scripts 前的门禁
param([Parameter(Mandatory=$true)][string]$Path)

$b = [IO.File]::ReadAllBytes($Path)
$bom = $b.Length -ge 3 -and $b[0] -eq 0xEF -and $b[1] -eq 0xBB -and $b[2] -eq 0xBF
$nonascii = @($b | Where-Object { $_ -gt 127 }).Count
$sha16 = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.Substring(0, 16)

# 关 1：无 BOM 且含非 ASCII → PS 5.1 会按 GBK 误读，直接拒
if (-not $bom -and $nonascii -gt 0) {
    Write-Host "REJECT: NOBOM + nonascii=$nonascii (PS5.1 GBK misread) sha16=$sha16"
    exit 2
}
# 关 2：严格 UTF-8 解码，坏字节序列直接拒
$strict = New-Object System.Text.UTF8Encoding($false, $true)
try { [void]$strict.GetString($b) }
catch { Write-Host "REJECT: invalid UTF-8 sha16=$sha16"; exit 3 }
# 关 3：PSParser 解析，语法错直接拒
$errs = $null
[void][System.Management.Automation.Language.Parser]::ParseFile($Path, [ref]$null, [ref]$errs)
if ($errs.Count -gt 0) { Write-Host "REJECT: ParserError=$($errs.Count) sha16=$sha16"; exit 4 }

Write-Host "OK bom=$bom nonascii=$nonascii sha16=$sha16 parseErr=0"
exit 0
```

三关分别挡住本次事故的三个必要条件：无 BOM + 中文、非法 UTF-8、语法错。哈希指纹一并输出，是为了让「落盘内容」和「自检过的内容」能对上——避免自检后又被人改了一行（这正是本系统另一条 `post-sha-mismatch` 检查在守的事）。

用法很简单：helper 先写到临时目录，自检 `exit 0` 后再拷进 `scripts`；自检不过就修到过为止。把纪律变成门禁，才是这次自伤的真正学费。

## 十、边界：这次没有动什么

复盘最怕把「做了什么」说清楚、把「没做什么」含糊过去。这里把边界列明（来源：`<workdir>/reports/ops/C5_WRAPUP_20261121.md` §5）：

- **判据目标 11 一字未动**。C5 复算仍是 `RESULT: C5 = 11`，源码段集 11 段、无删段。
- **巡检脚本零写入**。报告用的主巡检脚本本轮没有改动，段集不变。
- **另两个 FAIL 段的判法没动**。审批超时段的阈值、校验段的判法都零写入，该 FAIL 仍如实报红——没有为了「让数字好看」去调阈值或改判法。
- **只补 BOM，没迁目录、没删文件**。4 个 helper 留在 `scripts`，逐份留 `.bak`，可回滚。
- **未碰其他 agent 工作区**。补 BOM 仅限执行方自己的 `scripts` 目录，只读他人日志做三-agent 对照。

## 十一、收口：护栏自身成为故障源

把因果链连起来：

> 为修「失败被掩盖」改口径 → 写 4 个临时 helper 做复算 → helper 无 BOM 中文落进生产扫描目录 → 3-BOM 段把它们判 HIGH-RISK、打红 → blind 由 1 涨到 3、real 由 10 掉到 8、卡面过期到 8 → 判方独立实跑点名自伤 → 补 BOM 使 3-BOM 回 PASS、blind 掉到 2、实测回升到 9 → 定格卡面 8 并写明 blind 是运行期量。

这件事的教训不是「记得加 BOM」这么窄，而是两条更普适的经验：

1. **护栏也在被扫描的范围里**。「临时脚本」「非交付物」是人的心理标签，巡检不认。写护栏的人若把产物落在护栏自己的管辖范围里，就必须先过护栏的规矩——否则护栏会从「发现问题的人」变成「制造问题的源头」。
2. **把口径改诚实，和把系统改稳定，是两件事**。这次口径修正本身是对的（失败不再被掩盖），但它暴露出「落盘无门禁」这个更底层的问题。修一个判据的缺陷，顺手暴露了流程的缺陷——后者才是值得长久记住的。

判据的意义不在「段多」，而在「段的失败能被看见」。而当看见失败的机制本身成了失败源，唯一可靠的办法不是再修一次判据，而是给产生它的动作加一道门禁。
