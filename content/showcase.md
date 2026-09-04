---
title: "项目"
date: 2026-01-01T00:00:00+08:00
draft: false
summary: "我的开源项目与技术作品：AI Agent / MCP 工具、信息流聚合、极客菜谱"
---

这是我的开源项目与技术作品集中展示页。我专注 **Go 微服务架构、AI 大模型应用（MCP / Agent / RAG）与云原生工程**，这里收录了我在业余时间持续维护的项目。

## fluxio-mcp · 信息获取 MCP Server

> 让 Claude / Cursor / 各类 Agent 直接读取任意信息源的 MCP Server。

- **技术栈**：Python · FastMCP · httpx · BeautifulSoup
- **能力**：解析 RSS/Atom 订阅源（`fetch_rss`）、抓取网页并提取正文（`fetch_web`）、订阅源资源（`rss://`）
- **亮点**：纯标准库解析兼容命名空间；自动去噪提取正文；单测 + 真实 MCP stdio 握手 + 真实网络端到端三重验证；GitHub Actions 多版本 CI
- **链接**：[GitHub](https://github.com/IYABAO/fluxio-mcp)

## Fluxio · 信息流聚合工具

> 横向滚动切换订阅源的信息流桌面应用，支持一键收藏到 Obsidian。

- **技术栈**：Flutter (Windows) · Dart · RSS/Atom 解析 · 自包含 HTML 快照
- **能力**：多源信息流聚合、文章详情阅读、全量收藏（Markdown + HTML 双份）、源管理（分组/启停/编辑）
- **亮点**：SPA 滚动位置恢复、Obsidian 收件箱同步、RSS 解析支持 CDATA/实体/时间倒序
- **链接**：GitHub（整理中）

## CookingCoder · 极客菜谱

> 用程序员的方式做菜：把每道菜写成"可运行的代码"，火候、刀工都有明确度量。

- **技术栈**：Markdown · MCP · Mermaid 流程图 · MkDocs
- **能力**：40 道家常菜、五维标签（菜系/口味/人群/难度/时长）、`_spec.md` 度量库、MCP 工具、可视化流程
- **亮点**：火候/盐量等"常量定义"程序化，含「垃圾回收」「面向对象」式编程类比
- **链接**：[在线站点](https://cook.plbear.com/) · [GitHub](https://github.com/IYABAO/CookingCoder)

---

## 技术方向

我的日常工作与开源探索集中在三个方向：

| 方向 | 核心技能 | 代表产出 |
|------|----------|----------|
| **后端架构** | Go 微服务、gRPC、K8s、高并发 | PHP→Go 重构（QPS 800→5000+，延迟 15ms，0 脏读） |
| **AI 应用工程** | MCP、FastMCP、Agent、RAG、One-API | 企业级 MCP 服务、AI 模拟面试（越级率 0%） |
| **检索与数据** | Elasticsearch、Rollup、分库分表 | 百万级简历召回 <50ms、报表提速 80%+ |

> 更多技术文章见 [博客归档](/archives/)，完整经历见 [关于我](/about/)。
