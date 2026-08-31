---
title: "在线简历"
date: 2026-08-31
draft: false
---

<div style="border-bottom:2px solid #333;padding-bottom:12px;margin-bottom:16px;">
  <h1 style="margin:0 0 6px;">林壮 Allen</h1>
  <div style="color:#444;">资深后端架构师 / AI 应用开发 · 12 年互联网研发经验 · 现居杭州（接受远程）</div>
  <div style="color:#888;font-size:14px;margin-top:4px;">GitHub：<a href="https://github.com/IYABAO">github.com/IYABAO</a> · 邮箱：iyabao@vip.qq.com</div>
</div>

## 核心能力

- **12 年中台架构与微服务演进**：主导核心业务由 PHP 单体向 Go 分层微服务平滑演进，核心接口 QPS 从 800 跃升至 5000+（+625%），P99 延迟由 120ms 降至 15ms，实现 0 脏读故障与 100% 缓存一致性。
- **AI 智能体与 MCP 协议落地**：基于 FastMCP 构建企业级 Skills 与 MCP 服务，打通大模型与招聘系统的安全 Tool Call；主导 One-API 网关与 AI 模拟面试商业化闭环。
- **大数据检索与存储降本**：Elasticsearch 父子文档（Join Field）+ Rollup 预聚合，报表提速 80%+，每年节省存储成本数十万元。
- **云原生 DevOps 与研发提效**：K8s 调度、ELK 日志中台、Ingress 流量监控，基于 Claude Code 的 AI 辅助研发提效 40%。

## 技术栈

| 领域 | 技术 |
|---|---|
| 后端语言与框架 | Go（Gin / Gorm / Echo / gRPC / Protobuf）、PHP（Yii2 / Laravel / Swoole）、Python、Node.js |
| 存储与检索 | MySQL、MyCat 分库分表、Elasticsearch（Parent-Join / Rollup / Pipeline Agg）、Redis、RabbitMQ |
| AI 与大模型工程 | MCP 协议、FastMCP、One-API 网关、Prompt 状态机工程（STAR / Prefill）、Claude Code / Cursor |
| 云原生与 DevOps | Kubernetes、Docker、ELK、Ingress 流量监控、CI/CD 自动化流水线 |
| 生态与终端 | 微信生态（小程序 / 服务号 / 微信支付 / 开放平台）、多渠道消息防重推送 |

## 工作经历

### 杭州东方网升科技股份有限公司 · 资深后端开发 / Go 架构工程师
**2018.03 - 至今 | 杭州（最佳东方平台）**

- **中台架构演进与微服务重构**：主导简历服务、AI 网关及投递系统从 PHP 向 Go 分层微服务演进，制定 gRPC 跨服务通信标准与 SDK 规范，支撑百万级高并发招聘峰值。
- **AI 智能体与 MCP 服务落地**：基于 FastMCP 独立开发企业级 Skills 与 MCP 服务，实现大模型对招聘数据库的安全 Tool Call；搭建 One-API 网关落地 AI 模拟面试商业化。
- **大数据检索与分析中台**：基于 ES 父子文档与 Rollup 预聚合引擎，重构海量简历搜索引擎与全渠道招聘流量分析大盘。
- **工程效能革新**：推行规范化 AI 辅助研发工作流（Claude Code），高质量交付 20+ 核心业务模块，生产环境 0 故障。

### 福清绿林好汉电子商务 · PHP 工程师 / 技术合伙
**2016.06 - 2018.01（技术合伙 2016.10 - 2018.01）**

- 负责本地服务（上门洗车、社区便利店公众号）全栈架构与业务落地，基于 Yii2.0、MySQL、阿里云与 Apache 搭建。
- 引入微信自动授权登录与会员卡体系，实现会员充值与消费闭环。

### 逆思维网络科技（北京） · PHP 工程师 / 技术负责
**2013.12 - 2016.06（项目负责人 2015.01 - 2016.02）**

- 负责雅宝路中俄跨境电商平台（App 移动端 Wex5 + LAMP 架构）整体研发与技术把控。
- 搭建亚马逊云主机小型集群，进行 Apache 专项调优与 SQL 深度优化。
- 集成短信群发、邮件群发、Facebook 登录等第三方 API。

## 核心项目

### 1. 最佳东方 Skills 与 FastMCP 企业级服务研发（Python / FastMCP / LLM Agent）
- **挑战**：打破平台数据孤岛，让内外部 LLM 智能体安全、精准、低延迟地调用招聘与简历资产。
- **方案**：基于 FastMCP 将简历检索、人才画像匹配接口封装为标准 MCP 协议；设计 Token 鉴权与会话隔离中间件。
- **成效**：意图响应准确率提升 50%+。
- 📚 博客：[MCP 服务安全架构实践](/posts/2025-11-20-mcp-security-architecture/)

### 2. 最佳东方简历微服务中台与分布式重构（Go + gRPC + Redis + K8s）
- **挑战**：老 PHP 单体面对日均百万级流量查询与写入瓶颈凸显。
- **方案**：Go 分层微服务，写流量 100% 收敛至 Go、老 PHP 仅只读从节点；GORM AfterSave 钩子联动 Redis 缓存双向清理，失败触发 DB 回滚杜绝脏读；RabbitMQ + Swoole 异步削峰。
- **成效**：QPS 800 → 5000+，延迟 120ms → 15ms，零架构级线上故障。
- 📚 博客：[新版简历服务架构设计](/posts/2025-11-12-resume-service-architecture/)

### 3. 海量简历检索与全渠道招聘分析系统（Elasticsearch + MyCat + Rollup）
- **挑战**：传统关系型数据库无法支撑海量简历多条件组合深层检索，日志暴增导致报表卡顿。
- **方案**：ES 父子文档（Join Field）检索模型规避 Nested 写放大；Rollup 预聚合对冷数据降采样；MyCat 水平分表承载峰值写入。
- **成效**：百万级人才库 50ms 内深度召回；报表 3~5s → 200ms；存储成本大幅降低。
- 📚 博客：[Elasticsearch 检索实践](/posts/es-suo-yin-de-zeng-shan-gai-cha/)

### 4. AI 模拟面试智能体与大模型网关中台（Go + One-API + SSE + Prompt 工程）
- **挑战**：长文本多轮对话流程失控、高并发流式延迟、计费闭环。
- **方案**：Go 协程自研 HTTP SSE 代理引擎替代 PHP+Socket；System 元规则 + User 变量 + Assistant 预填三层 Prompt 结构锁死幻觉。
- **成效**：流程越级率 0%，TTFT < 500ms，打通会员充值计费对账闭环。
- 📚 博客：[AI 模拟面试智能体实现](/posts/2025-06-10-ai-interview-agent/)

## 教育背景

- **北航北海学院** · 软件工程 · 本科（2011 年毕业）

---

*本站自 2019 年起持续更新，沉淀后端架构、AI 工程与云原生的一线实践。更多文章见 [归档](/archives/)。*
