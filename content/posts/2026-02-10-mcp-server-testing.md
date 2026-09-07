---
title: "MCP Server 测试实践：握手、工具与端到端"
date: 2026-02-10T09:00:00+08:00
lastmod: 2026-02-10T09:00:00+08:00
draft: false
author: IYABAO
tags:
  - MCP
  - 测试
  - Python
categories:
  - 技术
summary: "MCP Server 怎么测？协议握手、工具声明、参数校验、端到端对话——从单元测试到真实 Client 联调的 MCP 测试体系，含 24 个测试用例的实战。"
---

# MCP Server 测试实践：握手、工具与端到端

MCP Server 是"给 LLM 用的 API"——它的消费者不是人，是模型。这意味着测试标准不一样：**不仅要测"功能对不对"，还要测"LLM 能不能用对"**。这篇文章是 fluxio-mcp 的测试体系：从单元测试到真实 Client 联调。

## 一、MCP Server 的测试分层

```
第 1 层：单元测试（工具函数级）
第 2 层：协议测试（MCP 握手/调用/错误）
第 3 层：工具契约测试（参数校验/输出结构）
第 4 层：端到端（真实 Client + 真实工具）
```

## 二、第 1 层：单元测试

测工具的核心逻辑（不经过 MCP 协议）：

```python
# tests/test_extract.py
async def test_extract_markdown_from_html():
    html = "<html><body><nav>导航</nav><article><h1>标题</h1><p>正文</p></article></body></html>"
    md = await extract_markdown(html)
    assert "导航" not in md          # 导航被去掉
    assert "# 标题" in md             # 转成 Markdown
    assert "正文" in md
```

**原则**：把纯逻辑（HTML→Markdown、URL 规范化）拆出来单测，不依赖网络。

## 三、第 2 层：协议测试

MCP 协议的关键环节：

```
initialize 握手（协议版本协商）
tools/list（工具声明）
tools/call（调用）
错误响应（工具不存在/参数错误）
```

```python
# tests/test_protocol.py
from fastmcp import Client

async def test_handshake():
    async with Client(transport=...) as client:
        tools = await client.list_tools()
        assert any(t.name == "fetch_urls" for t in tools)

async def test_call_tool():
    async with Client(transport=...) as client:
        result = await client.call_tool("fetch_urls", {"urls": ["http://127.0.0.1:9000/a"]})
        assert result.isError is False

async def test_unknown_tool():
    async with Client(transport=...) as client:
        result = await client.call_tool("not_exist", {})
        assert result.isError is True   # 协议级错误
```

**重点**：**每个工具都要过一遍协议调用**——单元测试通过 ≠ 协议层能调（参数序列化、返回结构可能有问题）。

## 四、第 3 层：工具契约测试

**契约 = LLM 依赖的东西**：

```
1. 工具名清晰（LLM 靠名字选择）
2. 参数 schema 准确（LLM 靠描述填参）
3. 输出结构稳定（LLM 靠结构消费）
```

```python
async def test_tool_schema():
    # 参数描述够不够 LLM 理解
    schema = get_tool_schema("fetch_urls")
    assert "urls" in schema.parameters["properties"]
    assert "最多 10 个" in schema.parameters["properties"]["urls"]["description"]

async def test_output_contract():
    result = await call("fetch_urls", {"urls": ["http://x/a"]})
    item = result[0]
    assert set(item.keys()) >= {"url", "title", "content"}   # 结构稳定
    assert item["content"].startswith("#")                    # Markdown 格式
```

**为什么契约测试重要**：LLM 消费输出时按 schema 理解——**输出结构一变，LLM 的理解就崩**（哪怕功能没错）。

## 五、第 4 层：端到端

真实场景：**LLM（Claude）→ MCP Client → Server → 真实 HTTP 请求**。

```bash
# 手动联调（开发时）
claude --mcp-config mcp.json
# 问："抓取 https://example.com 并总结"
# 看：模型是否选对工具、填对参数、消费对结果

# 自动化（CI）：模拟 LLM 行为
async def test_e2e_llm_flow():
    # 模拟 LLM 的工具调用序列（不走真实模型，走固定脚本）
    client = MCPClient()
    tools = await client.list_tools()
    picked = pick_tool(tools, "抓取 https://x.com")
    assert picked == "fetch_urls"        # 模型会选它吗（靠描述）
    result = await client.call_tool(picked, {"urls": ["https://x.com"]})
    assert result 可用                    # 结果能消费
```

**端到端的关键**：**验证"描述质量"**——LLM 会不会因为工具描述不清晰而选错/填错。这层测试最接近真实价值。

## 六、测试基础设施

### 本地 HTTP 测试服务（不依赖外网）

```python
# tests/server.py：本地起一个 HTTP 服务
# 提供：正常页 / 大页面 / 404 / 超时 / 反爬检测页
# 让测试稳定、可重复、CI 可跑
```

### CI 流水线

```yaml
# GitHub Actions
- uses: actions/setup-python
- run: pip install -e ".[test]"
- run: pytest -q          # 全量测试
- run: ruff check .       # lint
```

### 覆盖率

```bash
pytest --cov=fluxio_mcp --cov-report=term-missing
# 目标 85%+（协议层 100% 覆盖）
```

## 七、踩坑记录

1. **只测单元不测协议**：函数全过，但 tools/call 返回结构不对 → LLM 拿到"看似成功实际空"的结果
2. **测试依赖外网**：CI 偶发失败（网络抖动）→ 全换本地 HTTP 服务
3. **参数描述写不清**：测试发现 LLM 总是传错格式 → 描述里加"格式：xxx，最多 N 个"
4. **忽略错误路径**：只测成功路径 → 超时/反爬/编码错误全没覆盖

## 总结

MCP Server 测试的核心认知：

1. **四层体系**：单元 → 协议 → 契约 → 端到端
2. **契约测试是 MCP 独有**：输出结构稳定 = LLM 能消费
3. **描述质量可测**：端到端模拟 LLM 选工具，验证描述清晰度
4. **本地测试服务 + CI**：稳定、可重复、有门面

**MCP Server 的消费者是 LLM——测试标准是"LLM 能不能正确使用它"**，而不只是"功能对不对"。
