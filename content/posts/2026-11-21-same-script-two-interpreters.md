---
title: "同一脚本、两个解释器：一次被误诊三天的环境事故"
date: 2026-11-21T06:10:00+08:00
draft: false
tags: ["Python", "时区", "运维排障", "Windows", "踩坑记录"]
categories: ["技术复盘"]
description: "同一条巡检脚本，生产解释器有数、agent 侧只报 AUDITDB unavailable，被当成生产缺陷追了三天。本文记录误诊路径、两条互相独立的数据源如何证伪，以及为什么修法是回退固定 +08:00 而不是装 tzdata。"
---

> 本文数据来自本机 2026-11-21 的巡检脚本与三次直跑输出，命令、数字、退出码均为原文，可复跑。解释器路径、库路径、账号与内网信息已泛化为 `<user>` / `<agent-sandbox>` / `~/.<runtime>/governance/audit.db`。

## 一、现象：同一个脚本，两种结论

我有一条只读巡检脚本，每轮跑九段。段9 是 AUDIT，其中一行做 AUDITDB 对账：拿当天 00:00 到次日 00:00 的时间窗，只读打开本地治理库 `audit.db`，按 `decision` 分组数 ask / deny，再和日志侧解析出的 deny 数比差值。这一行是 print-only——不写行、不参与 FAIL 判定。

生产侧每天多轮，日志里长这样。11-20 的两行：

```text
[INFO] AUDITDB ask=8 deny=6 diff=log_resolved(8)-db_deny(6)=2 (print-only; not FAIL)
[INFO] AUDITDB ask=12 deny=10 diff=log_resolved(11)-db_deny(10)=1 (print-only; not FAIL)
```

11-19 也是数字：

```text
[INFO] AUDITDB ask=22 deny=19 diff=log_resolved(22)-db_deny(19)=3 (print-only; not FAIL)
```

我在 agent shell 里复跑同一条脚本：

```text
[INFO] AUDITDB unavailable (print-only; not FAIL)
```

同一个文件、同一份库、同一天。一边有数，一边 unavailable。没有异常退出、没有 FAIL、没有 traceback，整轮巡检照样 PASS。

这就是这次事故的形状：**它不是崩溃，是一行长得像正常输出的 INFO。**

## 二、误诊：三天里我一直在查错的东西

### 第一天：怀疑库

推理很顺：生产侧有数，说明数据源没坏；数据源没坏，那问题必然在我这一侧的读取链路上。于是查 `audit.db` 的路径展开、查 `file:...?mode=ro` 的只读 URI 写法、查是不是有别的进程占着锁。

结论：路径对，只读能打开，无锁冲突。

### 第二天：怀疑脚本

换个方式读同一个库（命令行客户端）是能读的，于是判断"脚本写错了"，回去读调用点。调用点是这样的：

```powershell
$dbCode = 'import sqlite3,sys,os,datetime,zoneinfo; d=datetime.date.fromisoformat(sys.argv[1]); z=zoneinfo.ZoneInfo("Asia/Shanghai"); ...'
$dbB64  = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($dbCode))
$dbOut  = @(& python -c "import base64;exec(base64.b64decode('$dbB64'))" $today 2>&1)
if ($dbOut -match '^AUDITDB ask=(\d+) deny=(\d+)$') {
    # 拼差值、打印正常行
} else {
    Write-Host '[INFO] AUDITDB unavailable (print-only; not FAIL)'
}
```

三个细节凑在一起，把证据烧干净了：

1. 真正的 Python 代码被 base64 包了一层，读脚本时看到的是一串 b64，`zoneinfo.ZoneInfo("Asia/Shanghai")` 藏在里面，肉眼扫不到。
2. `2>&1` 把 stderr 全部收进 `$dbOut` 变量——traceback 确实在变量里。
3. 下游正则只认 `AUDITDB ask=N deny=M` 一行；匹配不上就打成 unavailable。整段 traceback 一次都没被打印。

**证据在手上，被自己的日志格式吃掉了。** 这也是为什么它能躺三天：每一轮巡检都只是在输出一行"不可用"，没有任何一行字告诉你为什么不可用。

### 第三天：怀疑那个词

开始怀疑 `python` 这个词本身。跑一句：

```powershell
python -c "import sys;print(sys.executable);print(sys.version)"
```

打印出来的路径不是我脑子里那个安装包路径。三天里唯一没被检查的变量，是"我以为这台机器上只有一个 python"。

## 三、证伪：两条互相独立的数据源

误诊的根子是只有一个观测点。所以修的第一步不是改代码，是造第二个观测点，而且两个必须互相独立——一个回答"谁在跑"，一个回答"差别是不是就是原因"。

### 3.1 数据源 A：解释器指纹

```powershell
$py  = "C:\Users\<user>\...\Python312\python.exe"     # 生产侧
& $py -c "import sys;print(sys.version);print(sys.executable)"
& $py -c "import importlib.util as u;print('tzdata:', u.find_spec('tzdata') is not None)"
& $py -c "from zoneinfo import ZoneInfo;print(ZoneInfo('Asia/Shanghai'))"

$py2 = "<agent-sandbox>\python\python.exe"            # agent 沙箱
& $py2 -c "import sys;print(sys.version);print(sys.executable)"
& $py2 -c "import importlib.util as u;print('tzdata:', u.find_spec('tzdata') is not None)"
& $py2 -c "from zoneinfo import ZoneInfo;print(ZoneInfo('Asia/Shanghai'))"
```

结果：

| 解释器 | 版本 | tzdata | `ZoneInfo("Asia/Shanghai")` |
| --- | --- | --- | --- |
| 生产侧 | 3.12 | 有，2025.3 | 正常返回 |
| agent 沙箱 | 3.13.18 | 无 | 抛异常 |

机制不复杂：Windows 上的 zoneinfo 没有系统时区库可读，`ZoneInfo("Asia/Shanghai")` 只能回退到 `tzdata` 这个 pip 包；包里没有对应 key，就先抛 `ModuleNotFoundError`，再抛 `ZoneInfoNotFoundError`。同一段代码在 Linux 上常常撞不见这个问题，因为 `/usr/share/zoneinfo` 在那儿。

### 3.2 数据源 B：同一段代码 × 两种解释器 × 改前改后

把 base64 里那段代码原样解出来，不 mock、真读库，三个场景直跑，同一天、同一份库：

```text
===== BEFORE: original code on sandbox python 3.13.18 (no tzdata) =====
RC=1
ModuleNotFoundError: No module named 'tzdata'
...
zoneinfo._common.ZoneInfoNotFoundError: 'No time zone found with key Asia/Shanghai'
MARK=unavailable FALLBACK=N

===== AFTER: fixed code on py -3.12 (tzdata 2025.3) =====
RC=0
AUDITDB ask=14 deny=11
MARK=ok FALLBACK=N

===== AFTER: fixed code on sandbox python 3.13.18 (no tzdata) =====
RC=0
FALLBACK +08:00
AUDITDB ask=14 deny=11
MARK=ok FALLBACK=Y
```

为什么非要两条：

- 只有 A，可以反驳一句"环境不同，不代表会影响结果"。
- 只有 B，可以反驳一句"也许变的是别的东西"。

两条摆在一起，"解释器"这个变量就被钉死在同一分钟、同一份库、同一段代码上：换解释器，结论从 unavailable 变成 ok；不换解释器，改前改后同一把解释器结果稳定。

而生产侧那几天的日志一直有数（A 也证明它有包），所以"生产坏了"这个前提从第一天起就不成立。真正被搞错的是这一点：**我用来判断生产的那条复跑命令，压根没跑在生产的环境里。**

## 四、修法：为什么是回退，不是装包

最省事的方案是给沙箱解释器装个 tzdata。没选它，四条理由按重要性排：

**1. 装包修的是现场，不是代码。** 沙箱解释器的路径由宿主管理，版本随宿主升级，用户既没权限也不必往里装东西。今天装上了，宿主换一版就没了；换台机器又要再来一遍。这是"每次出事都要人肉修一次"的方案。

**2. 装包把隐含前提藏得更深。** 真正的缺陷是脚本把"环境里必须有 tzdata"写成了硬前提，而这条路径在巡检的关键路径上。装包只是把前提从代码搬进环境，以后换人、换机器、换 CI 再撞一次。修环境等于把 bug 挪进别人的机器配置里。

**3. 在这个场景，回退是等价，不是降级。** Asia/Shanghai 自 1991 年起无夏令时，全时固定 UTC+8。这段代码用这个时区只做一件事：把"当天 00:00"和"次日 00:00"换成毫秒时间戳，当 SQL 的 `ts>=? and ts<?` 边界。`datetime.timezone(timedelta(hours=8))` 与 `ZoneInfo("Asia/Shanghai")` 在这里算出的两个边界完全相同——不是"差不多"，是可验证的相等，§3.2 里两条路径给的 `ask=14 deny=11` 就是证据。

**4. 但降级必须留痕。** 静默回退是下一次事故的种子：哪天真的需要 DST 语义，静默回退会给出一个"看起来对"的错数。所以回退分支往 stdout 打一行 `FALLBACK +08:00`，调用点用正则抓住，拼到巡检那行末尾。降级可见、可统计、以后可告警。

代码本体：

```python
d = datetime.date.fromisoformat(sys.argv[1])
# Windows 缺 tzdata 时 ZoneInfo("Asia/Shanghai") 会抛 ModuleNotFoundError，
# 整段对账退化成 unavailable。回退固定 +08:00（中国无夏令时，与 Asia/Shanghai 全时等价），
# 并显式打印 FALLBACK 标记，让降级可见。
try:
    from zoneinfo import ZoneInfo
    z = ZoneInfo("Asia/Shanghai")
except Exception:
    z = datetime.timezone(datetime.timedelta(hours=8))
    print("FALLBACK +08:00")

lo = int(datetime.datetime.combine(d, datetime.time.min, tzinfo=z).timestamp() * 1000)
hi = int(datetime.datetime.combine(d + datetime.timedelta(days=1),
                                   datetime.time.min, tzinfo=z).timestamp() * 1000)
```

调用点透传标记：

```powershell
$tzNote = ''
if (($dbOut -join ' ') -match 'FALLBACK \+08:00') { $tzNote = ' FALLBACK +08:00' }
Write-Host ("[INFO] AUDITDB ask={0} deny={1} diff=... (print-only; not FAIL){2}" -f $ask, $deny, $tzNote)
```

**适用范围写清楚，比写"通用"更重要**：这个回退只对"已知无 DST 的固定偏移时区"成立。哪天要算 America/New_York，回退就是错的，那时要么装 tzdata，要么换成显式偏移表——但无论哪条路，`FALLBACK` 标记都得继续打，因为它是"这段代码现在走哪条路"的唯一凭证。

顺带几条约束：不 pip install、不改 PATH、不改系统环境；输出行格式 `AUDITDB ask=N deny=M` 一个字不动，下游正则不受影响；库还是 `mode=ro` 只读打开，没有写副作用。

## 五、验证：两把解释器都得跑，只有一把过不算修完

先把判定口径写死：**改前必须在无包解释器上失败，改后必须在两把解释器上都出数。** 只有一把过，那叫"换了个环境"，不叫修完。

三场景直跑结果见 §3.2：before × 沙箱 RC=1；after × 3.12 出 `AUDITDB ask=14 deny=11`，无标记；after × 沙箱出 `FALLBACK +08:00` + 同一组数字。

全量巡检再跑一遍，段9 回显原文：

```text
[INFO] AUDITDB ask=14 deny=11 diff=log_resolved(14)-db_deny(10)=4 (print-only; not FAIL)
```

没有 `FALLBACK` 标记——因为生产解释器有包，走的是真时区分支。这一条本身就是个交叉验证：**标记的有无，正好告诉你这一轮是谁在跑。**

段9 判定行：

```text
[9-AUDIT] PASS  WINDOW24H_TIMEOUT=21 ≤ 阈值30 CUMULATIVE_TIMEOUT=62（只读留证）
```

全程无 unavailable。改前留了备份（`daily-patrol.ps1.bak-20261121-tz`，175544 B），diff 是 1 file changed / 23 insertions / 2 deletions，净增 21 行，全部落在段9 AUDIT 块里——判据阈值、其他段、调度配置一个没碰。

## 六、三条能带走的

**1. 报"不可用"之前，先报"谁在跑"。** 任何 unavailable / 失败行，日志里都该带 `sys.executable` 和版本。这次如果那行是 `[INFO] AUDITDB unavailable python=3.13.18 ...`，三天的排查会变成三分钟。一条 `sys.executable` 的成本，比一次误诊低几个数量级。

**2. 复跑不是验证，复跑是另一个实验。** 换解释器、换 shell、换权限去跑生产脚本，得到的差异是**环境差异**，不是生产状态。这次的核心错误就是把"我复跑失败"读成了"生产异常"。以后复跑要单独记账：谁跑的、哪把解释器、哪份配置。复跑结果只能用来证伪假设，不能用来给生产定罪。

**3. 把吞掉的异常变成可数的信号。** 那段 `2>&1` 加一行正则的写法，把 traceback 收进变量又丢掉，等于把唯一的证据烧了。catch 之后要么打标记（像这次的 `FALLBACK`），要么抬退出码，要么把 stderr 首行落盘。**沉默的失败比报错的失败贵得多。**

最后留一句给"同一台机器"这个前提：同一台机器上，`python` 这个词可以指向两个完全不同的东西。所有"我这能跑啊"的对话，都该先附一句 `sys.executable`。
