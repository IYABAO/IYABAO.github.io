---
title: "fluxio-mcp 开发手记：从需求到开源"
date: 2026-01-13T09:00:00+08:00
lastmod: 2026-01-13T09:00:00+08:00
draft: false
author: IYABAO
tags:
  - MCP
  - 开源
  - Python
categories:
  - 技术
summary: "一个真实开源项目的完整旅程：为什么做、怎么设计、怎么测试、怎么开源。fluxio-mcp——给 LLM 装上一个可编程的网络信息流读取器。"
---

# fluxio-mcp 开发手记：从需求到开源

这篇文章记录 fluxio-mcp 从想法到开源的完整过程——一个给 LLM 提供"可编程信息获取能力"的 MCP Server。为什么做它、怎么设计、测试怎么覆盖、开源踩了什么坑。

## 一、为什么做

**背景**：做信息流工具（Fluxio）时，我发现一个真实痛点——

```
我：请整理今天 AI 领域的重要新闻
LLM：我的知识截止到 X 月，无法获取最新信息
```

LLM 的通用搜索能力（如果提供）和"信息流"差很远：

```
通用搜索：搜"关键词" → 返回网页 → LLM 自己读
信息流场景：需要的是"批量抓取 URL → 提取正文 → 结构化"
```

**需求成型**：

```
给 LLM 一组工具：
  1. 批量抓取 URL（多个源）
  2. 提取网页正文（去广告/导航）
  3. 转 Markdown（LLM 友好）
  4. 批量处理（一次喂多个链接）
```

**定位**：不是搜索，是"读取器"——**LLM 已经有链接，需要的是把链接变成可读的正文**。

## 二、架构设计

```
LLM（Claude / 任意 MCP Client）
   │  MCP 协议
   ▼
fluxio-mcp（Python + FastMCP）
   ├─ tools/fetch_urls   批量抓取 URL（并发）
   ├─ tools/extract_md   网页 → Markdown 正文
   ├─ tools/read_batch   批量读取 + 摘要
   └─ tools/search_news  信息流源聚合
   │
   ▼
HTTP 请求（httpx + 重试 + 限速）
```

**设计决策**：

| 决策 | 原因 |
|---|---|
| FastMCP | 装饰器极简、中间件、Python 生态 |
| httpx 并发 | 批量场景 IO 密集，并发是核心收益 |
| 可配置 UA | 部分站点反爬，UA 是基本尊重 |
| 超时 + 重试 | 网络不可靠，工具不能挂 |
| 输出纯 Markdown | LLM 消费友好（HTML 会污染上下文） |

## 三、核心实现

```python
@mcp.tool()
async def fetch_urls(urls: list[str]) -> list[dict]:
    """批量抓取 URL 内容，返回标题+正文(Markdown)。
    Args:
        urls: 要抓取的 URL 列表（最多 10 个）
    """
    async with httpx.AsyncClient(
        timeout=15,
        headers={"User-Agent": UA},
        follow_redirects=True,
    ) as client:
        results = await asyncio.gather(
            *(fetch_one(client, u) for u in urls[:10]),
            return_exceptions=True,
        )
    return [normalize(r) for r in results]
```

**关键点**：

1. **并发**：`asyncio.gather` 10 个 URL 并发，总耗时 ≈ 最慢的一个
2. **容错**：单个失败不影响整体（`return_exceptions`）
3. **上限**：`urls[:10]` 防滥用（工具级限流）
4. **降级**：正文提取失败 → 返回元数据（title/url），不让 LLM 拿空结果

## 四、测试怎么覆盖

开源项目没有测试 = 没有可信度。fluxio-mcp 的测试设计：

```python
# tests/test_fetch.py
class TestFetchUrls:
    async def test_single_url(self): ...
    async def test_multiple_urls(self): ...      # 并发正确性
    async def test_invalid_url(self): ...        # 容错
    async def test_timeout_fallback(self): ...   # 超时降级
    async def test_max_limit(self): ...          # 数量上限
    async def test_markdown_extraction(self): ... # 正文提取质量
```

**测试策略**：

```
✅ 用本地 HTTP 测试服务（不依赖真实网站，CI 稳定）
✅ 覆盖"边界"：空列表、非法 URL、超时、超大页面
✅ 覆盖"契约"：输出结构稳定（LLM 依赖 schema）
```

**CI**：GitHub Actions，push 自动跑 `pytest`——**开源项目的门面是 CI 绿**。

## 五、开源的坑

### 坑 1：README 是门面，别随便写

```
❌ 只有一句"给 LLM 用的抓取工具"
✅ 清晰的定位 + 安装 + 快速开始 + 工具清单 + 截图
```

### 坑 2：License 必须先定

```
MIT：最宽松，别人能放心用（推荐开源起步）
Apache-2.0：带专利条款（大公司友好）
GPL：传染（不适合工具类）
```

### 坑 3：示例比文档有用

```bash
# README 里给"10 秒跑起来"的示例
uvx fluxio-mcp 或 clone 后 python -m fluxio_mcp
# 让用户 30 秒内看到效果，比 1000 字文档有用
```

### 坑 4：版本与发布

```
✅ 语义化版本（0.1.0 → 0.2.0 → 1.0.0）
✅ 发布到 PyPI（pip install 即用）
✅ CHANGELOG 记录每次变更
```

## 六、收获

```
工程上：
  一个完整的产品级 MCP Server 的打磨流程
  （设计 → 实现 → 测试 → 文档 → 发布）
面试价值：
  "我开源过一个 MCP 工具" vs "我了解 MCP"
  ——后者是知识，前者是证据
```

## 总结

fluxio-mcp 的核心认知：

1. **开源项目的起点是"自己的真实痛点"**——不是追热点，是解决问题
2. **设计决策要写出来**：为什么 FastMCP、为什么并发、为什么 Markdown 输出
3. **测试是开源的门面**：CI 绿 + 边界覆盖 = 可信
4. **README/License/示例**是开源的"交付物"：代码好但没人用 = 白写

**开源不是"把代码放网上"，是"把问题、决策、过程一起交付"。** 过程的价值不比代码低。
