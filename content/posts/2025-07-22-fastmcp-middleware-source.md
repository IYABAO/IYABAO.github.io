---
title: "FastMCP 源码级剖析：中间件机制是怎么工作的"
date: 2025-07-22T09:00:00+08:00
lastmod: 2025-07-22T09:00:00+08:00
draft: false
author: IYABAO
tags:
  - MCP
  - FastMCP
  - Python
  - 源码
categories:
  - 技术
summary: "用 FastMCP 写了半年企业级 MCP 服务，决定读一遍源码：装饰器如何变成工具定义、session 生命周期、中间件洋葱模型、鉴权注入点。读完你对 MCP 服务的掌控力完全不同。"
---

# FastMCP 源码级剖析：中间件机制是怎么工作的

用 FastMCP 做了半年企业级 MCP 服务（简历检索、人才画像的 Tool Call），一直在"会写但不懂"。直到把源码读了一遍，才真正理解它的中间件机制、工具注册原理和鉴权注入点。这篇文章是我的源码阅读笔记。

## 一、FastMCP 的整体结构

```
fastmcp/
├── server/           # Server 核心：工具注册、session 管理、协议处理
│   ├── server.py     # FastMCP 主类
│   ├── session.py    # 一次 MCP 会话的生命周期
│   └── middleware/   # 中间件（鉴权/日志/错误处理）
├── tools/            # Tool 定义与参数解析
├── types.py          # MCP 协议类型（InitializeRequest 等）
└── transports/       # stdio / sse / streamable_http
```

## 二、装饰器背后发生了什么

我们平时写：

```python
@mcp.tool()
def search_resume(keyword: str, city: str = "") -> str:
    """搜索简历。"""
    return json.dumps(search_es(keyword, city))
```

`@mcp.tool()` 做的事：

```python
def tool(self, name=None, **kwargs):
    def decorator(fn):
        tool = Tool.from_function(fn, name=name, **kwargs)  # 1. 函数转 Tool
        self._tool_manager.add_tool(tool)                    # 2. 注册到工具管理器
        return fn                                            # 3. 原函数不变
    return decorator
```

**关键在 `Tool.from_function`**：

```python
@classmethod
def from_function(cls, fn, ...):
    # 1. 用 inspect.signature 解析函数签名
    signature = inspect.signature(fn)
    # 2. 参数 + 类型注解 + docstring → JSON Schema（tools/list 返回的就是它）
    parameters = schema_for(signature)
    # 3. docstring → 工具描述（LLM 决定调用哪个工具就看这个）
    description = parse_docstring(fn.__doc__)
    # 4. 参数名到实际调用的映射
    return cls(name=..., parameters=parameters, fn=fn)
```

**洞见**：工具的 JSON Schema **完全由函数签名 + 类型注解 + docstring 推导**。这就是为什么：
- 参数必须写类型注解（`str`/`int`/`list`）——Schema 生成依赖它
- docstring 第一行写清楚"做什么"——LLM 选工具靠它
- 复杂类型（Pydantic 模型）也能自动转 Schema

## 三、Session：一次连接的生命周期

MCP 是"连接 → 初始化 → 调用工具 → 断开"。`Session` 管理这一切：

```python
class Session:
    def __init__(self, ...):
        self.context = Context()          # 会话上下文
        self.initialized = False

    async def handle_request(self, request: Request):
        if isinstance(request, InitializeRequest):
            self.initialized = True
            return self.server.get_initialize_result()
        if not self.initialized:
            raise RuntimeError("not initialized")   # 协议强制：先初始化再干活
        # 路由到具体处理器
        return await self.dispatch(request)
```

**鉴权注入点就在这里**：`handle_request` 是每个请求的必经之路，鉴权中间件挂在这层，就能覆盖所有工具调用。

## 四、中间件：洋葱模型

FastMCP 中间件是**洋葱模型**（和 FastAPI 的 middleware 同款思路）：

```
请求进来
  ▼
[鉴权中间件]  ── 校验 token，失败 401
  ▼
[日志中间件]  ── 记录请求入参
  ▼
[错误处理]    ── try 工具调用
  ▼
工具函数
  ▼
[错误处理]    ── 异常转 MCP 错误码
  ▼
[日志中间件]  ── 记录耗时/结果
  ▼
[鉴权中间件]  ── 响应（可选审计）
  ▼
请求出去
```

实现本质（简化）：

```python
class MiddlewareChain:
    def __init__(self, middlewares):
        self._middlewares = middlewares

    async def __call__(self, request):
        async def run(index):
            if index >= len(self._middlewares):
                return await self._handler(request)   # 最内层 = 真正的工具调用
            mw = self._middlewares[index]
            return await mw(request, lambda: run(index + 1))  # next 往下走
        return await run(0)
```

**自研鉴权中间件**（我们线上的实现）：

```python
@server.middleware
async def auth_middleware(request, next):
    token = request.headers.get("Authorization", "").removeprefix("Bearer ")
    if not verify_token(token):
        raise McpError("INVALID_TOKEN", "未授权访问")
    request.context.user_id = get_user_id(token)   # 把用户身份注入上下文
    return await next(request)                     # 放行
```

**要点**：上下文（`request.context`）是中间件传递信息的通道——鉴权把 `user_id` 写进去，工具函数里 `ctx.user_id` 直接取，数据隔离就做完了。

## 五、工具调用的完整链路

```
LLM → tools/call {name: search_resume, arguments: {...}}
  │
  ▼
Server.handle_tool_call
  ├─ 1. 校验工具存在（_tool_manager.get_tool(name)）
  ├─ 2. 参数校验（JSON Schema 校验 + Pydantic 转换）
  ├─ 3. 中间件链（鉴权/日志）
  ├─ 4. 执行 fn（同步函数自动跑线程池，防阻塞事件循环）
  └─ 5. 结果序列化（TextContent / ImageContent）返回
```

**同步函数自动跑线程池**：FastMCP 检测到 fn 是同步函数，会用 `run_in_executor` 包一层——我们 ES 查询是同步库，这个细节保证不阻塞整个服务。

## 六、生产落地建议（读完源码后的结论）

1. **鉴权一定挂中间件**，别在工具函数里各自校验——一个注入点覆盖全部工具
2. **工具描述用心写**：LLM 是"读描述选工具"，描述差 = 调用率低
3. **参数校验交给类型注解**：Pydantic 模型做参数，复杂结构也能校验
4. **错误转 MCP 错误码**：别让异常裸奔，业务错误转成结构化错误返回给 LLM
5. **资源（Resources）和工具（Tools）分开**：低频大块数据用资源，操作类用工具

## 总结

FastMCP 的优雅在于**把"LLM 调用函数"这件事做成了工程**：

1. 函数签名 → JSON Schema，声明即协议
2. Session 管生命周期，初始化强约束
3. 中间件洋葱模型，横切关注点（鉴权/日志）一个入口
4. 上下文透传，身份和数据隔离随手可得

**读源码最大的收获：MCP 服务不是"写工具函数"，是"设计协议 + 控制面"。** 理解了中间件，你就能在 FastMCP 上长出自己的企业级能力。
