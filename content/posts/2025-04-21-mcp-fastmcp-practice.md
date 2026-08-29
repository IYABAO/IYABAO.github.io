---
title: "MCP 协议入门与实战：基于 FastMCP 构建企业级 Skills 服务"
date: 2025-04-21T10:00:00+08:00
draft: false
tags: ["MCP", "AI", "FastMCP", "Skills", "Python", "大模型"]
categories: ["AI架构"]
summary: "MCP（Model Context Protocol）协议入门与实战，基于 FastMCP 框架构建企业级 Skills 服务，让大模型安全调用招聘平台的结构化数据，实现 AI 智能体的工具调用能力。"
keywords: ["MCP", "FastMCP", "AI", "企业级Skills", "工具调用"]
---

MCP（Model Context Protocol）是 Anthropic 提出的开放协议，让大模型能安全地调用外部工具和数据。2025年4月我们基于 FastMCP 构建了招聘平台的企业级 Skills 服务，让 AI 智能体能调用简历检索、人才匹配、职位查询等工具。今天把入门和实战经验分享出来。

## 一、MCP 是什么

MCP 是大模型和外部工具之间的标准通信协议，类似 OpenAI 的 Function Calling，但更开放、更标准化：

- **Tools**：大模型可以调用的工具（如搜索简历、查询职位）
- **Resources**：大模型可以读取的资源（如简历详情、公司信息）
- **Prompts**：预定义的提示词模板

支持的传输方式：
- **stdio**：本地进程间通信，适合桌面端 AI 工具
- **HTTP/SSE**：网络传输，适合服务端部署

## 二、FastMCP 快速上手

FastMCP 是 Python 的 MCP 框架，类似 FastAPI，用装饰器定义工具：

```python
from fastmcp import FastMCP

mcp = FastMCP("招聘平台 Skills")

@mcp.tool()
def search_resumes(keyword: str, city_id: int = None, experience_min: int = 0, page: int = 1, page_size: int = 20) -> dict:
    """
    搜索简历，按关键词、城市、工作经验筛选。

    Args:
        keyword: 搜索关键词，如"PHP开发"
        city_id: 城市ID，杭州=2，上海=1
        experience_min: 最低工作年限
        page: 页码，从1开始
        page_size: 每页数量，最大50
    """
    # 调用招聘平台 API
    result = resume_api.search(keyword, city_id, experience_min, page, page_size)
    return {"total": result.total, "list": result.list}

@mcp.tool()
def get_resume_detail(resume_id: int) -> dict:
    """获取简历详情，包含基本信息、工作经历、教育经历、技能。"""
    resume = resume_api.get_detail(resume_id)
    return resume.to_dict()

@mcp.tool()
def match_candidates(job_id: int, top_n: int = 10) -> dict:
    """
    根据职位匹配候选人，返回最匹配的N个候选人。

    Args:
        job_id: 职位ID
        top_n: 返回数量，最大20
    """
    candidates = match_api.match(job_id, top_n)
    return {"candidates": candidates}

if __name__ == "__main__":
    mcp.run(transport="http")  # HTTP 服务模式
```

## 三、企业级设计

### 鉴权与安全

MCP 服务不能让大模型随意调用，要加鉴权和数据隔离：

```python
from fastmcp import FastMCP, Context

mcp = FastMCP("招聘平台 Skills")

# 鉴权中间件
@mcp.middleware("tool_call")
async def auth_middleware(ctx: Context, call_next):
    # 从请求头获取 Token
    token = ctx.request.headers.get("Authorization", "")
    if not token:
        raise PermissionError("缺少鉴权 Token")

    # 验证 Token，获取企业信息
    company = verify_token(token)
    if not company:
        raise PermissionError("Token 无效")

    # 把企业信息存入上下文，工具函数可以读取
    ctx.context["company_id"] = company.id
    ctx.context["permissions"] = company.permissions

    return await call_next(ctx)

@mcp.tool()
def search_resumes(ctx: Context, keyword: str) -> dict:
    company_id = ctx.context["company_id"]
    # 只能搜索本企业可见的简历
    result = resume_api.search(keyword, company_id=company_id)
    return result
```

### 数据脱敏

返回给大模型的数据要脱敏，防止敏感信息泄露：

```python
@mcp.tool()
def get_resume_detail(resume_id: int) -> dict:
    resume = resume_api.get_detail(resume_id)
    # 脱敏：手机号、邮箱只显示部分
    return {
        "id": resume.id,
        "name": resume.name,
        "phone": mask_phone(resume.phone),  # 138****1234
        "email": mask_email(resume.email),  # a***@example.com
        "work_experiences": resume.work_experiences,
        "skills": resume.skills,
    }
```

### 限流与监控

```python
@mcp.middleware("tool_call")
async def rate_limit_middleware(ctx: Context, call_next):
    company_id = ctx.context.get("company_id")
    key = f"mcp:rate:{company_id}"
    count = redis.incr(key)
    if count == 1:
        redis.expire(key, 60)
    if count > 100:  # 每分钟最多100次调用
        raise RateLimitError("调用频率超限")

    # 记录调用日志
    log_tool_call(company_id, ctx.tool_name)

    return await call_next(ctx)
```

## 四、部署

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["python", "server.py"]
```

部署在 K8s，通过 HTTP/SSE 对外提供服务，AI 智能体（Claude/Cursor/自研）配置 MCP 服务地址即可调用。

## 五、踩坑经验

1. **Tool 描述很重要**：大模型靠 docstring 理解工具用途，描述要清晰准确，包含参数说明和示例，否则大模型不会正确调用
2. **返回数据要精简**：返回给大模型的数据不要太大，Token 有限且贵。只返回必要字段，大字段（如完整简历）按需获取
3. **错误处理要友好**：工具调用失败时返回清晰的错误信息，大模型能根据错误信息调整调用方式
4. **流式传输**：长耗时工具（如批量简历解析）用流式返回进度，大模型能实时反馈给用户

## 六、总结

MCP 企业级 Skills 服务核心：

1. **FastMCP 快速开发**：装饰器定义工具，类似 FastAPI，开发效率高
2. **鉴权安全**：Token 鉴权 + 企业数据隔离 + 数据脱敏，防止越权和泄露
3. **限流监控**：每个企业独立限流，调用日志可追溯
4. **工具设计**：描述清晰、参数合理、返回精简、错误友好
5. **部署运维**：HTTP/SSE 模式部署，K8s 编排，弹性扩缩容

MCP 是 AI 智能体连接外部世界的标准协议，未来会像 REST API 一样普及。提前布局 MCP 服务，让企业数据和能力能被 AI 安全调用，是 AI 时代的重要基础设施。
