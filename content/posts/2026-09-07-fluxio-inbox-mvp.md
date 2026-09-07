---
title: "Fluxio 收件箱：给本地 App 加一个「任何来源一键收藏」的能力"
date: 2026-09-07T10:30:00+08:00
lastmod: 2026-09-07T10:30:00+08:00
draft: false
author: IYABAO
tags:
  - Flutter
  - MCP
  - Obsidian
  - Chrome扩展
  - 开源
categories:
  - 技术
summary: "用 dart:io 零依赖给本地 App 加收件服务：浏览器扩展 / 剪贴板 / 脚本三入口一键收藏到 Obsidian，Token 鉴权 + 协议白名单 + 失败降级，附完整实现与踩坑。"
cover:
  image: images/posts/fluxio-inbox/cover.svg
  alt: "Fluxio 收件箱架构概览"
---

# Fluxio 收件箱：给本地 App 加一个「任何来源一键收藏」的能力

> 我的信息流聚合工具 [Fluxio](https://github.com/IYABAO/Fluxio)（Flutter 桌面 + 移动端）一直有个痛点：**站内收藏很顺，但微信、今日头条、任意网页想收藏到 Obsidian，链条是断的。** 这篇文章记录我给它补上「收件箱」能力的过程：零新依赖的本地收件服务 + 剪贴板捕获 + MV3 浏览器扩展，任意来源一键投递，走与站内收藏 **100% 相同的链路**。

## 一、需求拆解

先看场景矩阵：

| 场景 | 用户动作 | 约束 |
|---|---|---|
| 网页（电脑端） | 浏览器点一下扩展图标 | 无 |
| 微信（电脑端） | 复制文章链接 | 剪贴板可用 |
| 今日头条（手机） | 复制链接 → 投递页 | 手机连不上 127.0.0.1 |
| 微信（手机） | 分享给收件入口 | 封闭生态，需官方 API |

我的设计原则很简单：**Fluxio 是本地应用、无后端，所以收件服务也应该是本地的一个极简 HTTP 服务**——`dart:io` 自带 `HttpServer`，零第三方依赖。手机端和企业微信放 P2/P3（局域网投递页、企微官方 API），先把电脑端三个入口做透。

![收件箱整体架构](images/posts/fluxio-inbox/01-arch.svg)

## 二、核心：本地收件服务（dart:io 零依赖）

Fluxio 启动时在 `127.0.0.1:8730` 起一个 `HttpServer`（端口被占自动 +1 探测），提供两个端点：

- `POST /api/inbox`：投递一条收藏
- `GET /api/health`：扩展探测服务存活

**Token 鉴权**：应用首次启动生成随机 32 位 token 存本地（`Random.secure()` + `base64Url`），扩展配置页粘贴即可。请求头带 `X-Inbox-Token`，不匹配返回 401。

**URL 白名单**：只接受 `http://` / `https://`，拒绝 `file://`、`data:`、`javascript:` 等协议注入。

```dart
// 收件处理核心（节选）
Future<({bool ok, String? error, String? record})> saveUrl(
  String url, {
  String source = '网页',
  String? title,
}) async {
  if (!_isHttpUrl(url)) {
    return (ok: false, error: 'INVALID_URL', record: null);
  }
  // 1. 抓取 + 提取（尽力而为：失败仍收藏链接，保证一键可用）
  var content = '';
  var html = '';
  try {
    final fetched = await _fetch(url);
    final extracted = _extract(fetched); // <title> + 去脚本样式纯文本
    content = extracted.$1;
    html = extracted.$2;
  } catch (e) {
    debugPrint('inbox fetch failed for $url: $e');
  }
  // 2. 复用现有收藏链路：saveClip → md + 自包含 HTML → Obsidian 收件箱
  final info = WebPageInfo(
    url: url,
    title: title ?? _firstLine(content),
    content: content,
    html: html,
  );
  try {
    final files = await _obsidianStore.saveClip(info, sourceTitle: source);
    return (ok: true, error: null, record: files.first.uri.pathSegments.last);
  } catch (e) {
    return (ok: false, error: '$e', record: null);
  }
}
```

**关键设计是"降级"**：抓取或提取失败不代表收藏失败——链接照收（`type` 回退为仅链接收藏）。用户一键收藏的确定性 > 内容的完整性，这是收件体验的第一原则。

## 三、剪贴板捕获：复制链接 = 弹条确认

微信电脑端最常见的动作是「复制链接」。Fluxio 每 2 秒轮询一次剪贴板（Flutter `Clipboard.getData`），发现**新的** `http(s)` 链接就弹一条 SnackBar：

```dart
// 剪贴板钩子（节选）
Timer.periodic(const Duration(seconds: 2), (_) async {
  if (_clipboardPromptVisible || !mounted) return;
  final data = await Clipboard.getData(Clipboard.kTextPlain);
  final text = data?.text?.trim() ?? '';
  if (text.isEmpty || text == _lastClipboard) return;
  _lastClipboard = text;
  final url = _extractUrl(text); // 正则提取首个 URL
  if (url == null) return;
  _clipboardPromptVisible = true;
  ScaffoldMessenger.of(context).showSnackBar(
    SnackBar(
      content: Text('📥 检测到链接：$url'),
      action: SnackBarAction(label: '收藏', onPressed: () async {
        final result = await inboxServer.saveUrl(url, source: '剪贴板');
        // 提示 已收藏 / 收藏失败
      }),
    ),
  );
});
```

两个细节：**只提示不自动收藏**（避免误投）；**记录上次内容去重**（同一链接只弹一次）。正则用普通字符串而非 raw string 有个坑——字符类里要包含中文标点 `，。；` 截断 URL，`r'...\'...'` 在 Dart raw string 里反斜杠不转义单引号会直接报语法错误，换成普通字符串 `'...\'...'` 才正确。

## 四、浏览器扩展：MV3 最小权限

Chrome/Edge 共用一套 MV3 扩展（`tool/extension/`），权限只申请 `activeTab` + `storage`：

```json
{
  "manifest_version": 3,
  "name": "Fluxio 收藏助手",
  "permissions": ["activeTab", "storage"],
  "action": { "default_popup": "popup.html" },
  "options_ui": { "page": "options.html" }
}
```

- **点击图标** → `chrome.tabs.query` 取当前页 URL/标题 → `fetch('http://127.0.0.1:8730/api/inbox')` 带 token 投递 → popup 显示 `✅ 已收藏 → 文件名`
- **选项页**：配置收件地址 + token（Fluxio 设置页一键复制）
- 无 `host_permissions`：运行时向本机地址发请求即可，权限面最小

```
扩展(popup) ──POST /api/inbox──▶ 本地收件服务 ──▶ saveClip ──▶ Obsidian 收件箱
                                   (127.0.0.1:8730)
```

## 五、安全边界与复用清单

| 风险 | 对策 |
|---|---|
| 本地服务被其他进程投递 | 随机 token 鉴权 + 仅绑定 loopback（不暴露局域网） |
| 协议注入 | URL 白名单（仅 http/https） |
| 剪贴板误报 | 只提示不自动收藏 + 去重 |
| 抓取失败丢收藏 | 降级为纯链接收藏，失败可解释（`SAVE_FAILED`/`INVALID_URL`） |

**复用清单（现有代码零改动）**：`ObsidianStore.saveClip`（唯一收藏入口）、`WebPageInfo` 模型、剪贴板历史服务。新代码只有 1 个服务文件 + 扩展目录 + 两处 UI 钩子，这是「给旧 App 加新能力」比较舒服的形态。

## 六、Roadmap

- [x] **MVP**：本地收件 API + 设置页 Token + 剪贴板捕获 + MV3 扩展（analyze 0 error / 20 测试全过）
- [ ] **P2**：局域网投递页（手机头条复制链接 → 手机浏览器粘贴投递）
- [ ] **P3**：企业微信官方 API + 云函数 + 云端队列轮询（微信手机端分享，零封号风险，不碰个人微信机器人）

## 七、总结

这次实践最大的收获是**"收件"这个能力的形态**：

1. **本地 App 不需要后端也能有收件能力**——`dart:io HttpServer` 零依赖，127.0.0.1 足够
2. **收件体验的第一原则是确定性**——失败要降级而不是报错，一键可用比内容完整更重要
3. **新能力要长在旧链路上**——复用 `saveClip` 一个入口，代码零改动，测试全绿

Fluxio 完整代码在 GitHub（MIT）：[github.com/IYABAO/Fluxio](https://github.com/IYABAO/Fluxio)（含收件箱设计文档 `docs/inbox-design.md`）。如果你也在做本地工具 + Obsidian 工作流，欢迎交流。

---

*首发于 [plbear.com](https://www.plbear.com) · 更多 MCP / Agent / 全栈实战见 [博客归档](https://www.plbear.com/archives/)*
