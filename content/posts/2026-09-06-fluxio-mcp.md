---
title: "手写一个信息获取 MCP Server：fluxio-mcp 从零到开源"
date: 2026-09-06T10:00:00+08:00
draft: false
tags: ["MCP", "FastMCP", "Python", "AI", "LLM", "开源", "Agent"]
categories: ["AI架构"]
summary: "从零手写一个基于 FastMCP 的信息获取 MCP Server：RSS 解析、网页转 Markdown、免 Key 搜索，让 Claude/Cursor 等 Agent 直接读取任意信息源。含架构设计、踩坑记录、三层验证体系与接入教程。"
keywords: ["MCP", "FastMCP", "fluxio-mcp", "Agent", "LLM", "RSS", "Markdown", "网页搜索"]
cover:
  image: images/posts/fluxio-mcp/cover.svg
  alt: "fluxio-mcp 开源项目封面"
---

在用 Cursor / Claude 写代码、查资料时，我经常遇到一个尴尬：**LLM 明明联网能力很弱，却又要靠它去"读"网页、订阅源、文档**。传统做法是让 Agent 自己抓网页——但抓回来的是满屏导航、脚本、广告的原始 HTML，模型根本读不动，更别提结构化的标题层级和代码块了。

于是我用 FastMCP 手写了一个信息获取 MCP Server：**fluxio-mcp**。RSS 解析、网页正文提取、网页转 Markdown、免 Key 搜索，四个工具 + 一个资源，让 LLM 像读本地文件一样读取任意信息源。今天把从设计到上线的全过程拆开讲。

## 一、为什么是 MCP，而不是直接写爬虫

MCP（Model Context Protocol）是大模型和外部工具之间的标准通信协议。相比让 Agent 各自实现一套"抓网页"逻辑，MCP 的价值在于：

- **标准化**：工具定义、参数校验、返回格式全部走协议，客户端零适配
- **即插即用**：Claude Desktop、Cursor、任意 Agent 配置一行命令就能接入
- **安全边界**：Agent 只能调用暴露的工具，不能随意访问系统

FastMCP 是 Python 的 MCP 框架，类似 FastAPI 之于 HTTP——用装饰器定义工具，几行代码就是一个 Server。

## 二、架构设计

![fluxio-mcp 架构图](/images/posts/fluxio-mcp/01-arch.svg)

整体分三层：**LLM 客户端 → fluxio-mcp Server → 数据源/服务**。

- 客户端通过 MCP stdio 协议与 Server 通信（本地进程，无需网络端口）
- Server 暴露 4 个工具 + 1 个资源，每个工具只做一件事
- 数据源全部走 HTTP，不依赖任何付费 API

设计原则就一条：**工具要"小"**。RSS 归 RSS、网页归网页、搜索归搜索，模型可以根据任务自由组合——搜索到链接再抓正文，比一个"全功能抓取"工具更可控。

## 三、核心实现

### 3.1 Server 骨架

```python
from fastmcp import FastMCP

mcp = FastMCP("fluxio-mcp")

@mcp.tool()
def fetch_rss(url: str, limit: int = 15) -> str:
    """解析 RSS/Atom 订阅源，返回文章列表。"""
    ...

@mcp.tool()
def search_web(query: str, max_results: int = 8) -> str:
    """搜索网页，返回标题/链接/摘要。"""
    ...
```

装饰器一挂，工具自动进入协议。这是 FastMCP 最爽的地方——**零协议样板代码**。

### 3.2 网页转 Markdown：比纯文本高一个维度

`fetch_web` 提取纯文本，`fetch_web_md` 则是把网页转成**结构化 Markdown**：

```python
def _convert(node, in_pre=False):
    # 块级标签递归，输出后补空行
    if name in ("h1", "h2", ...):
        return f"\n{_HEADING[name]} {inner}\n"
    if name == "pre":
        return f"\n```{lang}\n{code}\n```\n"   # 代码块带语言
    if name in ("ul", "ol"):
        return f"- {item}\n"                    # 列表
    if name == "a":
        return f"[{inner}]({href})"             # 链接
    ...
```

纯文本方案在 LLM 场景有个致命伤：**截断即失真**——正文超过 max_chars 时，纯文本从任意位置切断，段落语义全丢；Markdown 保留标题层级和代码块，即使截断，模型也能抓住章节骨架。

### 3.3 免 Key 搜索：Bing 主端点 + DuckDuckGo 降级

```python
_SEARCH_ENDPOINTS = [
    ("bing", "https://www.bing.com/search"),
    ("duckduckgo", "https://html.duckduckgo.com/html/"),
]
```

先打 Bing（`mkt=zh-CN`，国内直连），失败降级 DuckDuckGo（海外）。都不需要 API Key，解析结果页的 `li.b_algo` 结构即可。这避免了给 Agent 配搜索引擎 Key 的额外成本。

## 四、踩过的三个坑

**坑 1：DuckDuckGo 在国内是连接超时，不是被反爬。** 最初用 DuckDuckGo 做唯一端点，真实搜索直接 `ConnectTimeout`。排查 UA、加重试都没用——是网络层不可达。于是把 Bing 提为主端点，DuckDuckGo 只做海外降级。**排查方向错了会浪费很多时间，先确认是网络问题还是应用问题**。

**坑 2：主题生成的锚点链接污染标题。** 博客主题给每个标题生成 `<a class="headerlink">#</a>`，转 Markdown 后标题变成 `## 一、MCP 是什么#`。修复：转换时识别并跳过 `headerlink` / `anchor` 类链接。**转换器要认识"网站自己加的东西"**。

**坑 3：正文噪音比想象的多。** `nav/header/footer/aside/script` 都要先 decompose 再提取，否则摘要里全是菜单文字。这个清洗列表是逐站实测补出来的，现在抓本站文章、阮一峰周刊都干净。

## 五、典型工作流

![搜索到沉淀的完整链路](/images/posts/fluxio-mcp/02-workflow.svg)

一条典型链路：`search_web` 搜到目标链接 → `fetch_web_md` 转 Markdown → LLM 读结构化的内容做总结/写代码 → 产出物直接沉淀成笔记或博客。**搜索、抓取、阅读、沉淀，四个工具正好闭环**。

## 六、三层验证体系

![三层验证体系](/images/posts/fluxio-mcp/03-verify.svg)

项目坚持"**能跑 ≠ 能用**"：每个工具必须过三层验证才敢说完成——

1. **单元测试（21 个用例）**：解析器用固定 HTML 样本断言，覆盖边界（空结果、超长、噪音、uddg 解码）
2. **真实网络端到端**：抓阮一峰 Atom、抓本站文章、Bing 真实搜索——验证的是"真实世界能用"
3. **MCP 协议握手**：stdio 启动真实 Server，核对工具注册清单 + 真实调用返回

push 后 GitHub Actions 会在 Python 3.10/3.11/3.12 三版本自动重跑全部测试，回归零遗漏。

## 七、接入你的 Claude / Cursor

```json
// claude_desktop_config.json
{
  "mcpServers": {
    "fluxio": {
      "command": "fluxio-mcp",
      "args": []
    }
  }
}
```

Cursor 在 `Settings → MCP → Add` 里填同样的命令即可。装好之后，你可以在对话里直接说：

> 帮我看看阮一峰周刊最近三期讲了什么 → `fetch_rss`
> 搜一下"MCP 中文教程"并总结前三篇 → `search_web` + `fetch_web_md`

## 八、Roadmap 与下一步

- [x] 网页转 Markdown（保留标题/列表/代码块/表格）
- [x] 免 Key 搜索（Bing + DuckDuckGo）
- [ ] 多 URL 批量抓取
- [ ] 发布 PyPI（`pip install fluxio-mcp`）

项目已开源：**github.com/IYABAO/fluxio-mcp**（MIT License，CI 自动跑测试）。欢迎 star、提 issue、贡献代码。

---

写这个项目最大的收获是：**Agent 能力的瓶颈往往不在模型，而在"信息获取"这一环**。把 RSS、网页、搜索这些基础能力做成标准工具，等于给任何 LLM 装上了"任意门"。下一步我准备把 fluxio-mcp 接入自己的信息流工具 Fluxio，让收藏的内容自动走一遍"搜索 → 阅读 → 沉淀"的闭环，到时候再写一篇实战记录。
