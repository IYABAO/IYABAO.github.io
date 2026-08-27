---
title: "MCP Skills 开发实战：从零构建招聘领域 Skills 服务"
date: 2025-07-28T10:00:00+08:00
draft: false
tags: ["MCP", "Skills", "FastMCP", "Python", "AI", "大模型", "招聘"]
categories: ["AI架构"]
summary: "基于 FastMCP 从零构建招聘领域 MCP Skills 服务的完整实战，涵盖项目结构、工具定义、资源管理、提示词模板、鉴权安全、部署运维，以及在 Claude/Cursor 中的实际使用体验。"
---

MCP 协议火了之后，各种 MCP Server 层出不穷，但大多数是通用工具（文件系统、数据库、浏览器）。真正有价值的是**领域专属的 MCP Skills**——把你所在行业的专业知识和业务能力封装成 MCP 服务，让大模型能像领域专家一样工作。2025年我们基于 FastMCP 构建了招聘领域的 MCP Skills 服务，今天把完整开发过程分享出来。

## 一、什么是 MCP Skills

先明确概念：
- **MCP Server**：实现了 MCP 协议的服务端，提供 Tools/Resources/Prompts
- **Skills**：MCP Server 里的具体能力集合，通常围绕一个领域或场景
- **FastMCP**：Python 的 MCP 开发框架，类似 FastAPI，用装饰器快速定义工具

一个 MCP Server 可以包含多个 Skills，比如我们的招聘 MCP Server 包含：简历搜索 Skill、职位管理 Skill、人才匹配 Skill、面试评估 Skill。

## 二、技术选型

| 维度 | 选择 | 原因 |
|------|------|------|
| 语言 | Python 3.11 | FastMCP 是 Python 框架，AI 生态好 |
| 框架 | FastMCP | 类似 FastAPI，开发效率高，社区活跃 |
| 部署 | Docker + K8s | HTTP/SSE 模式，弹性扩缩容 |
| 鉴权 | API Key + JWT | 企业级服务，多租户隔离 |
| 缓存 | Redis | 工具结果缓存，减少重复计算 |
| 监控 | Prometheus + Grafana | 调用量、延迟、错误率监控 |

## 三、项目结构

```
recruitment-mcp/
├── skills/                    # 各个 Skill
│   ├── __init__.py
│   ├── resume_search.py       # 简历搜索 Skill
│   ├── job_management.py      # 职位管理 Skill
│   ├── talent_match.py        # 人才匹配 Skill
│   └── interview_eval.py      # 面试评估 Skill
├── clients/                   # 内部服务客户端
│   ├── resume_client.py       # 简历服务 API 客户端
│   ├── job_client.py          # 职位服务 API 客户端
│   └── match_client.py        # 匹配服务 API 客户端
├── middleware/                 # 中间件
│   ├── auth.py                # 鉴权中间件
│   ├── rate_limit.py          # 限流中间件
│   └── logging.py             # 日志中间件
├── config.py                  # 配置
├── server.py                  # MCP Server 入口
├── requirements.txt
├── Dockerfile
└── README.md
```

## 四、核心开发

### 4.1 MCP Server 初始化

```python
# server.py
from fastmcp import FastMCP
from skills.resume_search import register as register_resume_skills
from skills.job_management import register as register_job_skills
from skills.talent_match import register as register_match_skills
from skills.interview_eval import register as register_interview_skills
from middleware.auth import auth_middleware
from middleware.rate_limit import rate_limit_middleware
from middleware.logging import logging_middleware
from config import settings

# 创建 MCP Server
mcp = FastMCP(
    name="招聘平台 Skills",
    instructions="""
    这是最佳东方招聘平台的 MCP Skills 服务。
    提供简历搜索、职位管理、人才匹配、面试评估等招聘领域能力。
    使用前需要有效的 API Key，每个企业只能访问自己的数据。
    """,
)

# 注册中间件
mcp.add_middleware(auth_middleware)
mcp.add_middleware(rate_limit_middleware)
mcp.add_middleware(logging_middleware)

# 注册各个 Skill
register_resume_skills(mcp)
register_job_skills(mcp)
register_match_skills(mcp)
register_interview_skills(mcp)

if __name__ == "__main__":
    # HTTP/SSE 模式部署
    mcp.run(transport="http", host="0.0.0.0", port=8000)
```

### 4.2 简历搜索 Skill

这是最核心的 Skill，让大模型能搜索招聘平台的简历库。

```python
# skills/resume_search.py
from fastmcp import FastMCP
from clients.resume_client import ResumeClient
from typing import Optional, List, Dict
from pydantic import BaseModel, Field

# 搜索结果的数据模型
class ResumeSummary(BaseModel):
    resume_id: int = Field(description="简历ID")
    name: str = Field(description="姓名（脱敏后）")
    title: str = Field(description="当前职位")
    experience_years: float = Field(description="工作年限")
    city: str = Field(description="所在城市")
    education: str = Field(description="最高学历")
    current_company: str = Field(description="当前公司")
    match_score: float = Field(description="匹配度分数（0-100）")

class SearchResult(BaseModel):
    total: int = Field(description="总匹配数")
    page: int = Field(description="当前页码")
    page_size: int = Field(description="每页数量")
    resumes: List[ResumeSummary] = Field(description="简历列表")


def register(mcp: FastMCP):
    client = ResumeClient()

    @mcp.tool()
    def search_resumes(
        keyword: str = Field(description="搜索关键词，如'Go开发''前端工程师''架构师'"),
        city: Optional[str] = Field(default=None, description="城市名称，如'杭州''上海''北京'"),
        experience_min: Optional[int] = Field(default=None, description="最低工作年限"),
        experience_max: Optional[int] = Field(default=None, description="最高工作年限"),
        education: Optional[str] = Field(default=None, description="最低学历：大专/本科/硕士/博士"),
        salary_min: Optional[int] = Field(default=None, description="期望最低薪资（K/月）"),
        page: int = Field(default=1, ge=1, description="页码，从1开始"),
        page_size: int = Field(default=20, ge=1, le=50, description="每页数量，最大50"),
    ) -> SearchResult:
        """
        搜索简历库，按关键词、城市、工作经验、学历、薪资等条件筛选。
        返回匹配的简历摘要列表（手机号、邮箱等敏感信息已脱敏）。

        使用场景：
        - 为某个职位搜索合适的候选人
        - 了解某个技术方向的人才市场情况
        - 统计某个城市/岗位的人才数量

        示例：
        - 搜索杭州的 Go 开发工程师：search_resumes(keyword="Go开发", city="杭州")
        - 搜索5年以上经验的架构师：search_resumes(keyword="架构师", experience_min=5)
        """
        # 调用内部简历服务 API
        result = client.search(
            keyword=keyword,
            city=city,
            experience_min=experience_min,
            experience_max=experience_max,
            education=education,
            salary_min=salary_min,
            page=page,
            page_size=page_size,
        )

        return SearchResult(
            total=result["total"],
            page=page,
            page_size=page_size,
            resumes=[ResumeSummary(**r) for r in result["list"]],
        )

    @mcp.tool()
    def get_resume_detail(
        resume_id: int = Field(description="简历ID，从搜索结果中获取"),
    ) -> Dict:
        """
        获取简历详情，包含基本信息、工作经历、教育背景、项目经历、技能标签。
        敏感信息（手机号、邮箱、身份证）已脱敏，需要查看完整信息请在平台操作。

        使用场景：
        - 深入了解某个候选人的详细经历
        - 评估候选人与职位的匹配度
        - 为面试准备问题
        """
        detail = client.get_detail(resume_id)
        # 脱敏处理
        detail["phone"] = mask_phone(detail.get("phone", ""))
        detail["email"] = mask_email(detail.get("email", ""))
        return detail

    @mcp.tool()
    def get_resume_stats(
        keyword: str = Field(description="统计关键词"),
        city: Optional[str] = Field(default=None, description="城市"),
    ) -> Dict:
        """
        获取简历库统计数据，包括人才数量、工作经验分布、学历分布、薪资分布。
        用于了解人才市场情况。

        示例：
        - 了解杭州 Go 开发的人才市场：get_resume_stats(keyword="Go开发", city="杭州")
        """
        return client.get_stats(keyword=keyword, city=city)


def mask_phone(phone: str) -> str:
    if not phone or len(phone) < 7:
        return phone
    return phone[:3] + "****" + phone[-4:]

def mask_email(email: str) -> str:
    if not email or "@" not in email:
        return email
    name, domain = email.split("@", 1)
    if len(name) <= 2:
        return name[0] + "***@" + domain
    return name[0] + "***" + name[-1] + "@" + domain
```

**关键点**：
1. **description 要详细**：工具描述、参数描述、使用场景、示例都要写清楚，模型靠这个理解什么时候用、怎么用
2. **Pydantic 模型**：用 Pydantic 定义返回数据结构，类型安全，模型能理解返回字段含义
3. **敏感信息脱敏**：手机号、邮箱等敏感信息必须脱敏，不能直接返回给模型
4. **参数约束**：用 Field 的 ge/le 限制参数范围，防止模型传入不合理的值
5. **分页限制**：page_size 最大 50，防止模型一次请求太多数据

### 4.3 人才匹配 Skill

```python
# skills/talent_match.py
from fastmcp import FastMCP
from clients.match_client import MatchClient
from typing import List, Dict
from pydantic import BaseModel, Field

class MatchResult(BaseModel):
    resume_id: int
    name: str
    title: str
    match_score: float = Field(description="总匹配度（0-100）")
    skill_match: float = Field(description="技能匹配度")
    experience_match: float = Field(description="经验匹配度")
    education_match: float = Field(description="学历匹配度")
    salary_match: float = Field(description="薪资匹配度")
    match_reason: str = Field(description="匹配原因说明")

def register(mcp: FastMCP):
    client = MatchClient()

    @mcp.tool()
    def match_candidates_for_job(
        job_id: int = Field(description="职位ID"),
        top_n: int = Field(default=10, ge=1, le=20, description="返回最匹配的N个候选人"),
    ) -> List[MatchResult]:
        """
        根据职位要求匹配候选人，返回最匹配的N个候选人及匹配度分析。
        匹配维度包括：技能匹配、经验匹配、学历匹配、薪资匹配。

        使用场景：
        - 职位发布后自动推荐合适的候选人
        - 对比多个候选人与职位的匹配度
        - 了解职位要求与人才市场的匹配情况
        """
        results = client.match_by_job(job_id, top_n)
        return [MatchResult(**r) for r in results]

    @mcp.tool()
    def match_jobs_for_resume(
        resume_id: int = Field(description="简历ID"),
        top_n: int = Field(default=10, ge=1, le=20, description="返回最匹配的N个职位"),
    ) -> List[Dict]:
        """
        根据简历匹配职位，返回最匹配的N个职位。
        用于为候选人推荐合适的职位。
        """
        return client.match_by_resume(resume_id, top_n)

    @mcp.tool()
    def analyze_match(
        resume_id: int = Field(description="简历ID"),
        job_id: int = Field(description="职位ID"),
    ) -> Dict:
        """
        深度分析某份简历与某个职位的匹配度，包括各维度得分、优势、不足、改进建议。

        使用场景：
        - 面试前评估候选人与职位的匹配度
        - 为候选人提供求职建议
        - 分析职位要求是否合理
        """
        return client.analyze_match(resume_id, job_id)
```

### 4.4 Resources：职位 JD 资源

除了 Tools，还可以定义 Resources，让模型能读取职位 JD 作为上下文。

```python
# skills/job_management.py
from fastmcp import FastMCP
from clients.job_client import JobClient

def register(mcp: FastMCP):
    client = JobClient()

    # 定义资源模板：job://{job_id}
    @mcp.resource(
        "job://{job_id}",
        name="职位详情",
        description="根据职位ID获取职位详情，包含职位名称、职责、要求、薪资、公司信息",
        mime_type="application/json",
    )
    def get_job(job_id: int) -> dict:
        """获取职位详情"""
        return client.get_job(job_id)

    # 定义资源列表：所有在招职位
    @mcp.resource(
        "jobs://active",
        name="在招职位列表",
        description="获取当前企业所有在招职位的列表",
        mime_type="application/json",
    )
    def list_active_jobs() -> list:
        """获取在招职位列表"""
        return client.list_active_jobs()

    # Tools：创建/更新职位
    @mcp.tool()
    def create_job(
        title: str = Field(description="职位名称"),
        department: str = Field(description="部门"),
        salary_min: int = Field(description="最低薪资（K/月）"),
        salary_max: int = Field(description="最高薪资（K/月）"),
        city: str = Field(description="工作城市"),
        description: str = Field(description="职位描述和要求"),
    ) -> dict:
        """
        创建新职位。创建后需要在平台审核发布。
        注意：职位描述要包含职责、要求、加分项等信息。
        """
        return client.create_job(title, department, salary_min, salary_max, city, description)
```

### 4.5 Prompts：面试评估提示词模板

```python
# skills/interview_eval.py
from fastmcp import FastMCP

def register(mcp: FastMCP):
    @mcp.prompt()
    def technical_interview_evaluation(
        resume_summary: str,
        job_requirements: str,
        interview_notes: str,
    ) -> str:
        """
        技术面试评估模板，根据简历、职位要求、面试记录生成面试评估报告。

        参数：
        - resume_summary: 候选人简历摘要
        - job_requirements: 职位要求
        - interview_notes: 面试记录（面试官的笔记）

        使用场景：面试结束后，快速生成结构化的面试评估报告。
        """
        return f"""
        你是一位资深的技术面试官，请根据以下信息生成面试评估报告。

        【候选人简历摘要】
        {resume_summary}

        【职位要求】
        {job_requirements}

        【面试记录】
        {interview_notes}

        【评估要求】
        请从以下维度评估：
        1. 技术能力（编程语言、框架、系统设计、算法）
        2. 项目经验（项目复杂度、个人贡献、技术深度）
        3. 问题解决能力（分析问题、解决思路、学习能力）
        4. 沟通表达（逻辑清晰、表达准确、团队协作）
        5. 文化匹配（价值观、工作风格、职业规划）

        每个维度给出1-5分评分和简要说明，最后给出总体评价和录用建议（强烈推荐/推荐/待定/不推荐）。
        输出格式为 Markdown。
        """
```

## 五、中间件

### 鉴权中间件

```python
# middleware/auth.py
from fastmcp import Context
from config import settings

async def auth_middleware(ctx: Context, call_next):
    # 从请求头获取 API Key
    api_key = ctx.request.headers.get("X-API-Key", "")
    if not api_key:
        raise PermissionError("缺少 API Key")

    # 验证 API Key，获取企业信息
    company = verify_api_key(api_key)
    if not company:
        raise PermissionError("API Key 无效")

    # 把企业信息存入上下文
    ctx.context["company_id"] = company.id
    ctx.context["company_name"] = company.name
    ctx.context["permissions"] = company.permissions

    return await call_next(ctx)
```

### 限流中间件

```python
# middleware/rate_limit.py
import redis
from fastmcp import Context

redis_client = redis.Redis()

async def rate_limit_middleware(ctx: Context, call_next):
    company_id = ctx.context.get("company_id", "unknown")
    key = f"mcp:rate:{company_id}"

    # 每分钟最多 100 次调用
    count = redis_client.incr(key)
    if count == 1:
        redis_client.expire(key, 60)
    if count > 100:
        raise RateLimitError("调用频率超限，每分钟最多100次")

    return await call_next(ctx)
```

## 六、部署

### Dockerfile

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["python", "server.py"]
```

### K8s 部署

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: recruitment-mcp
spec:
  replicas: 2
  selector:
    matchLabels:
      app: recruitment-mcp
  template:
    metadata:
      labels:
        app: recruitment-mcp
    spec:
      containers:
      - name: mcp
        image: registry.example.com/recruitment-mcp:latest
        ports:
        - containerPort: 8000
        resources:
          requests:
            cpu: "500m"
            memory: "512Mi"
          limits:
            cpu: "2"
            memory: "2Gi"
        env:
        - name: RESUME_SERVICE_URL
          value: "http://resume-service:8080"
        - name: JOB_SERVICE_URL
          value: "http://job-service:8080"
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 10
          periodSeconds: 30
---
apiVersion: v1
kind: Service
metadata:
  name: recruitment-mcp
spec:
  selector:
    app: recruitment-mcp
  ports:
  - port: 8000
    targetPort: 8000
```

## 七、在 Claude/Cursor 中使用

### Claude Desktop 配置

在 Claude Desktop 的配置文件 `~/.claude.json` 里添加：

```json
{
  "mcpServers": {
    "recruitment": {
      "url": "https://mcp.example.com/sse",
      "headers": {
        "X-API-Key": "your-api-key-here"
      }
    }
  }
}
```

重启 Claude Desktop，就能在对话里使用招聘 Skills 了。

### Cursor 配置

Cursor Settings → MCP → Add new MCP server：

```json
{
  "mcpServers": {
    "recruitment": {
      "url": "https://mcp.example.com/sse",
      "headers": {
        "X-API-Key": "your-api-key-here"
      }
    }
  }
}
```

### 使用示例

在 Claude 里输入："帮我搜索杭州的 Go 开发工程师，5年以上经验，然后分析前3个候选人的匹配度"

Claude 会自动：
1. 调用 `search_resumes(keyword="Go开发", city="杭州", experience_min=5)`
2. 拿到结果后，对前3个简历调用 `get_resume_detail(resume_id=...)`
3. 调用 `analyze_match(resume_id=..., job_id=...)` 分析匹配度
4. 生成综合分析报告

整个过程不需要用户手动调用工具，Claude 自主规划和执行。

## 八、踩坑经验

1. **Tool description 决定一切**：初期 description 写得简单，模型不知道什么时候用这个工具。后来加了使用场景、示例、注意事项，模型调用准确率从 60% 提升到 95%
2. **返回结果要精简**：初期返回完整简历（几千字），模型上下文很快就满了。改成返回摘要 + 详情按需获取，上下文占用减少 80%
3. **参数默认值很重要**：没有默认值的参数，模型每次都要"猜"，容易传错。常用参数（page、page_size、city）都给默认值
4. **错误信息要友好**：工具执行失败时，返回"搜索失败"模型不知道怎么处理。改成"搜索失败：城市'杭州'不存在，请检查城市名称"，模型会自动修正参数重试
5. **敏感信息必须脱敏**：初期返回了真实手机号，有数据泄露风险。加了统一脱敏中间件，所有返回结果自动脱敏
6. **限流不能少**：模型有时会循环调用工具（比如分页搜索时陷入死循环），加了每分钟100次的限流，防止滥用
7. **日志要完整**：MCP 调用是黑盒，出问题不知道模型调了什么、传了什么参数。加了完整的调用日志（工具名、参数、结果、耗时），方便排查
8. **版本管理**：工具接口变更会影响所有使用者，不能随便改。加了版本号（v1/search_resumes），新版本不兼容时保留旧版本一段时间

## 九、总结

MCP Skills 开发核心：

1. **领域知识是核心价值**：通用工具谁都能做，领域专属的 Skills 才是护城河。把招聘领域的专业知识（简历搜索、人才匹配、面试评估）封装成 MCP，让大模型成为招聘专家
2. **FastMCP 开发效率高**：类似 FastAPI 的装饰器模式，定义工具、资源、提示词都很简单，专注业务逻辑
3. **Tool description 要写好**：这是 MCP 开发最重要的事，description 决定模型会不会用、用得对不对
4. **返回结果要精简**：大模型上下文有限，返回摘要 + 详情按需获取，不要一次返回全部
5. **安全不能忽视**：鉴权、限流、脱敏、审计，企业级 MCP 服务这些都是必须的
6. **部署 HTTP/SSE 模式**：适合远程部署、多用户共享，比 stdio 模式更适合企业级服务
7. **日志和监控**：MCP 调用是黑盒，完整的日志和监控是排查问题的基础
8. **版本管理**：接口变更要兼容，不能随便改，用版本号管理

MCP 的价值在于"把专业能力标准化、可复用"。以前你要为每个 AI 应用单独对接业务系统，现在封装成 MCP Skills，任何支持 MCP 的 AI 工具（Claude、Cursor、ChatGPT、自研 Agent）都能直接用，一次开发处处使用。对于企业来说，把内部业务能力封装成 MCP Skills，是让 AI 真正落地业务的关键一步。
