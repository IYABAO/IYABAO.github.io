---
title: "codeblock render probe 20261113（临时测试页，稍后删除）"
date: 2026-11-13T00:05:00+08:00
draft: false
---

PROBE-START

下面第一种是无语言标记的裸围栏代码块：

```
* main 7a23df0 [gitee/main: ahead 9]
PROBE-BARE-A
```

第二种带 powershell 语言标记：

```powershell
Get-ChildItem -Path . | Select-Object -First 3
PROBE-PS-B
```

第三种带 text 语言标记：

```text
plain text block line
PROBE-TEXT-C
```

PROBE-END
