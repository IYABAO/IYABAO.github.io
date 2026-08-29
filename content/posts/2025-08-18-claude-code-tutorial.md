---
title: "Claude Code 深度教程：从 CLI 命令到自定义 Skills 工作流"
date: 2025-08-18T10:00:00+08:00
draft: false
tags: ["Claude Code", "AI编程", "CLI", "Skills", "MCP", "研发效能", "教程"]
categories: ["工程效能"]
summary: "Claude Code 的深度使用教程，从基础 CLI 命令到高级技巧，涵盖项目理解、多文件重构、自定义 Skills、MCP 集成、调试排错、工作流优化，以及在 Go/PHP 微服务项目中的实战经验。"
keywords: ["Claude Code", "AI辅助开发", "Skills", "工作流"]
---

Claude Code 是 Anthropic 推出的命令行 AI 编程助手，2025年已经成为很多后端开发者的主力工具。它不是简单的代码补全，而是能在终端里自主理解项目、编辑文件、运行命令、调试排错的 AI Agent。我用 Claude Code 做了几个微服务重构项目，总结了一套从入门到精通的使用方法。今天把深度教程分享出来。

## 一、Claude Code 是什么

Claude Code 是运行在终端里的 AI 编程助手，核心特点：

1. **CLI 原生**：在终端里运行，和 Vim/Emacs/tmux 完美配合
2. **自主 Agent**：能自主规划任务、编辑文件、运行命令、看报错、修复，循环直到完成
3. **项目理解**：能读取整个项目结构、理解代码上下文、跨文件引用
4. **工具能力**：内置文件编辑、命令执行、搜索、git 操作，还能通过 MCP 扩展
5. **Claude 原生**：用 Claude 3.5/3.7 Sonnet/Opus，推理能力强，复杂任务完成度高

和 Cursor 的区别：Cursor 是 AI 原生 IDE（GUI），Claude Code 是 CLI 工具。喜欢命令行、用 Vim/Emacs、做后端开发的，Claude Code 更顺手；喜欢 GUI、做前端全栈的，Cursor 体验更好。

## 二、安装与配置

### 安装

```bash
# macOS
brew install claude-code

# 或用 npm
npm install -g @anthropic-ai/claude-code

# 验证安装
claude --version
```

### 认证

```bash
# 方式一：用 Anthropic API Key（按量付费）
export ANTHROPIC_API_KEY=sk-ant-xxx

# 方式二：订阅 Claude Pro/Max（含额度）
claude login
```

建议重度用户订阅 Max 计划（$20/月），有额度上限，比按量付费可控。

### 基础配置

创建 `~/.claude/settings.json`：

```json
{
  "permissions": {
    "allow": ["Read", "Write", "Edit", "Bash(git *)", "Bash(go *)", "Bash(make *)"],
    "deny": ["Bash(rm -rf /)", "Bash(:(){:|:&};:)"]
  },
  "model": "claude-3-5-sonnet-20241022",
  "max_uses": 50
}
```

- `permissions.allow`：允许执行的操作，常用命令加白名单，不用每次确认
- `permissions.deny`：禁止执行的危险操作
- `model`：默认模型，Sonnet 性价比高，复杂任务用 Opus
- `max_uses`：单次对话最大工具调用次数，防止死循环

## 三、基础使用

### 启动

```bash
# 在项目目录下启动
cd my-project
claude

# 启动时直接带任务
claude "给这个服务加一个健康检查接口"

# 用特定模型启动
claude --model opus "重构这个复杂函数"
```

### 常用命令

在 Claude Code 交互界面里：

| 命令 | 说明 |
|------|------|
| `/help` | 查看帮助 |
| `/clear` | 清空对话历史 |
| `/compact` | 压缩对话历史（上下文太长时用） |
| `/model` | 切换模型 |
| `/cost` | 查看当前对话的 token 用量和费用 |
| `/exit` | 退出 |
| `!命令` | 直接执行 shell 命令（如 `!git status`） |
| `@文件名` | 引用文件，让 Claude 关注这个文件 |
| `@符号名` | 引用代码符号（函数、类、变量） |

### 第一个任务

```bash
# 在 Go 项目里
claude "给 resume-service 加一个健康检查接口 /health，返回服务状态、版本、数据库连接状态"
```

Claude Code 会：
1. 读取项目结构，找到 resume-service 的代码
2. 理解现有代码风格和框架（Gin/Echo）
3. 编辑 handler 文件，添加 /health 接口
4. 编辑路由文件，注册路由
5. 运行 `go build` 验证编译通过
6. 运行 `go test` 跑测试
7. 如果有报错，自动修复，再跑一遍

整个过程不需要你手动操作，Claude 自主完成。你只需要看结果，不满意就说"这里改一下"。

## 四、高级技巧

### 4.1 项目理解

Claude Code 能读取整个项目，但上下文有限，要引导它关注重点：

```text
# 让 Claude 先理解项目结构
"先看一下这个项目的整体结构，主要有哪些服务，用了什么框架和中间件"

# 关注特定模块
"重点看一下 resume-service 的架构，handler/service/repository 分层是怎么设计的"

# 引用特定文件
"参考 @/internal/handler/resume.go 的风格，给 job-service 加类似的接口"
```

### 4.2 多文件重构

复杂重构涉及多个文件，要把任务拆清楚：

```text
"把 resume-service 的 CreateResume 接口从同步改成异步：
1. 接口接收请求后立即返回任务ID
2. 实际处理放到后台 goroutine
3. 加一个查询任务状态的接口 /resume/task/{id}
4. 任务状态存在 Redis 里
5. 加单测覆盖正常和异常场景

先看一下现有代码，然后告诉我你的实现方案，确认后再改"
```

**关键点**：
- 把需求说清楚，包含具体步骤
- 涉及外部依赖（Redis）要说明
- 要求加单测，保证质量
- "先看代码再说方案，确认后再改"——防止 Claude 直接改出问题

### 4.3 调试排错

Claude Code 最强大的场景之一是调试：

```text
# 贴报错日志
"这个服务启动报错了，帮我看看是什么问题：
[贴报错日志]
"

# 或者让它自己跑
"运行 make test，看看有什么测试失败，帮我修复"

# 复杂问题
"这个接口 P99 延迟突然从 50ms 升到 500ms，帮我排查一下。
先看最近的 git log 有什么变更，再看代码可能的性能瓶颈"
```

Claude 会自己运行命令、看日志、分析代码、定位问题、修复，然后再跑一遍验证。

### 4.4 代码审查

```text
"审查一下最近3次 commit 的代码变更，重点看：
1. 有没有安全问题（SQL注入、XSS、权限绕过）
2. 有没有性能问题（N+1查询、内存泄漏、锁竞争）
3. 有没有不符合项目规范的地方
4. 错误处理是否完善

按严重程度排序，给出具体的修改建议"
```

### 4.5 测试生成

```text
"给 resume-service 的 service 层加单元测试，要求：
1. 覆盖所有公开方法
2. 正常场景和异常场景都要覆盖
3. 用 mock 模拟 repository 层，不要连真实数据库
4. 用 testify 断言库
5. 测试覆盖率达到 80% 以上

先看一下现有代码和已有的测试风格，再开始写"
```

## 五、自定义 Skills

Claude Code 支持自定义 Skills，把常用的工作流固化下来。

### 创建 Skill

在项目根目录创建 `.claude/skills/` 目录，每个 Skill 是一个子目录，包含 `SKILL.md`：

```
my-project/
└── .claude/
    └── skills/
        ├── api-development/
        │   └── SKILL.md
        ├── bug-fix/
        │   └── SKILL.md
        └── code-review/
            └── SKILL.md
```

### Skill 示例：API 开发流程

```markdown
# .claude/skills/api-development/SKILL.md
---
name: api-development
description: 开发新 API 接口的标准流程，包含接口定义、参数校验、业务逻辑、错误处理、单测
---

# API 开发标准流程

当用户要求开发新 API 接口时，按以下流程执行：

## 1. 理解需求
- 确认接口的功能、输入、输出
- 确认权限要求（是否需要登录、角色权限）
- 确认是否有类似的现有接口可以参考

## 2. 查看现有代码
- 查看同模块的 handler 代码风格
- 查看路由注册方式
- 查看 service 层和 repository 层的模式
- 查看错误处理和参数校验的方式

## 3. 实现接口
按以下顺序实现：
1. **参数定义**：在 types 包定义请求和响应结构体，加 validate tag
2. **Handler**：参数校验、调用 service、格式化响应
3. **Service**：业务逻辑、事务管理、缓存操作
4. **Repository**：数据库操作
5. **路由注册**：在 router 里注册接口

## 4. 错误处理
- 参数错误返回 400，code=1
- 未登录返回 401，code=2
- 无权限返回 403，code=3
- 资源不存在返回 404，code=4
- 服务器错误返回 500，code=500

## 5. 单测
- Handler 层：用 httptest 测试，mock service
- Service 层：mock repository，覆盖正常和异常场景
- 覆盖率要求 80% 以上

## 6. 验证
- 运行 `go build ./...` 确认编译通过
- 运行 `go test ./...` 确认测试通过
- 运行 `go vet ./...` 确认没有静态检查问题

## 注意事项
- 遵循现有代码风格，不要引入新的依赖
- 敏感操作（删除、修改）要加权限校验
- 数据库操作用事务保证一致性
- 不要硬编码，配置放 config
```

### 使用 Skill

启动 Claude Code 后，它会自动发现 `.claude/skills/` 里的 Skills。当你说"开发一个新接口"时，Claude 会自动加载 api-development Skill，按标准流程执行。

也可以显式指定：

```text
"用 api-development skill 给 job-service 加一个批量更新职位状态的接口"
```

## 六、MCP 集成

Claude Code 支持 MCP，可以连接外部 MCP Server 扩展能力。

### 配置 MCP

在 `~/.claude.json` 或项目级 `.claude/settings.json` 里配置：

```json
{
  "mcpServers": {
    "recruitment": {
      "url": "https://mcp.example.com/sse",
      "headers": {
        "X-API-Key": "your-key"
      }
    },
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {
        "GITHUB_TOKEN": "ghp_xxx"
      }
    }
  }
}
```

### 使用 MCP 工具

配置后，Claude Code 就能使用 MCP Server 提供的工具。比如连接了 GitHub MCP 后：

```text
"查看一下我最近的 PR，找出有 review 意见但还没修改的，帮我逐个处理"
```

Claude 会调用 GitHub MCP 工具获取 PR 列表，筛选未处理的，然后逐个修改代码、提交、推送。

## 七、工作流优化

### 7.1 CLAUDE.md 文件

在项目根目录创建 `CLAUDE.md`，Claude Code 启动时会自动读取，作为项目级指令：

```markdown
# CLAUDE.md

## 项目概述
这是最佳东方招聘平台的后端微服务，用 Go + Gin + GORM 开发，部署在 K8s 上。

## 技术栈
- 语言：Go 1.22
- Web 框架：Gin
- ORM：GORM
- 数据库：MySQL 8.0
- 缓存：Redis 7
- 消息队列：RabbitMQ
- 服务发现：etcd
- 部署：K8s + ArgoCD

## 代码规范
- 分层架构：handler → service → repository
- 错误处理：用自定义 error，统一返回格式 {code, message, data}
- 参数校验：用 go-playground/validator
- 日志：用 zap，结构化日志
- 测试：用 testify，mock 用 mockery

## 常用命令
- 构建：make build
- 测试：make test
- 运行：make run
- 代码生成：make gen（mock、swagger）

## 注意事项
- 不要直接修改 main 分支，新建分支开发
- 数据库迁移用 golang-migrate，不要手动改表
- 敏感配置不要硬编码，从环境变量读
- 提交前跑 make lint 和 make test
```

有了 CLAUDE.md，Claude Code 不用每次都问"这个项目用什么框架"，直接就能上手。

### 7.2 任务拆分

大任务不要一次丢给 Claude，拆成小任务，每步验证：

```text
# 不好的方式
"把这个服务从 PHP 重写成 Go"

# 好的方式
"我们要把 apply-service 从 PHP 重写成 Go，分几步来：
第一步：先看一下 PHP 版的代码结构和业务逻辑，给我一个迁移方案
第二步：搭建 Go 项目骨架（目录结构、依赖、配置、启动脚本）
第三步：实现数据模型和 repository 层
第四步：实现 service 层
第五步：实现 handler 层和路由
第六步：加单测
第七步：写迁移文档和回滚方案

先做第一步，给我迁移方案，确认后再开始第二步"
```

每步完成后验证，再进行下一步，比一次让它做整个重构靠谱得多。

### 7.3 人工审核

Claude 生成的代码一定要审核，特别是：
- 安全相关（SQL、权限、加密）
- 并发相关（goroutine、锁、channel）
- 数据库事务
- 错误处理
- 性能敏感的代码

不要完全信任 AI，它会"一本正经地胡说八道"。审核重点是逻辑正确性和安全性，语法和风格 Claude 一般没问题。

## 八、实战案例

### 案例：微服务接口开发

任务：给 resume-service 加一个批量导出接口。

```text
我：用 api-development skill 加一个批量导出简历的接口，支持按条件筛选，导出 Excel，异步生成，完成后发通知。

Claude：（读取项目结构，理解现有代码）
好的，我理解需求了。这个接口涉及异步任务和文件生成，我的实现方案：
1. 接口 POST /resume/export，接收筛选条件，立即返回任务ID
2. 后台 goroutine 执行：查询数据 → 生成 Excel → 上传 OSS → 更新任务状态 → 发通知
3. 查询任务状态接口 GET /resume/export/{task_id}
4. 任务状态存在 Redis，任务记录存在 MySQL
5. Excel 生成用 excelize 库
6. 加单测覆盖

你看这个方案可以吗？

我：可以，开始实现。

Claude：（开始编辑文件，加 types、handler、service、repository、路由）
（运行 go build，编译通过）
（运行 go test，测试通过）
（运行 go vet，没有问题）

完成了，新增/修改了以下文件：
- internal/types/export.go（请求/响应类型）
- internal/handler/export.go（handler）
- internal/service/export.go（异步任务逻辑）
- internal/repository/export_task.go（任务持久化）
- internal/router/router.go（注册路由）
- internal/service/export_test.go（单测）

接口已经可以用了，你可以用 curl 测试一下：
curl -X POST http://localhost:8080/resume/export \
  -H "Content-Type: application/json" \
  -d '{"keyword":"Go开发","city":"杭州"}'
```

整个过程 5 分钟，比自己写快 5-10 倍，而且代码质量稳定。

## 九、踩坑经验

1. **上下文太长会"失忆"**：对话太长时，Claude 会忘记早期的上下文。用 `/compact` 压缩，或者开新对话，把关键信息贴进去
2. **不要让它直接跑危险命令**：虽然有 deny 列表，但还是要小心。涉及删除、覆盖、发布的命令，让它先确认再执行
3. **大文件编辑容易出错**：Claude 编辑大文件（>500行）时有时会漏内容。让它用小范围编辑，或者把大文件拆成小文件
4. **依赖版本问题**：Claude 可能会建议用不存在的 API 或过时的库。涉及第三方库时，让它先看 go.mod/package.json 里的版本，再写代码
5. **测试不要完全信**：Claude 写的测试有时会"放水"（断言太松、mock 不对）。一定要看测试代码，确认测试真的在验证逻辑
6. **git 操作要小心**：让 Claude 操作 git 时，它可能会强制推送、删除分支。涉及 git 操作时，先让它说要执行什么命令，确认后再执行
7. **API Key 安全**：不要把 API Key 写在代码里，Claude 可能会不小心提交到 git。用环境变量，CLAUDE.md 里说明
8. **费用控制**：重度使用 Claude Code，token 消耗很快。订阅 Max 计划比按量付费划算，用 `/cost` 随时看用量

## 十、总结

Claude Code 深度使用核心：

1. **CLI 原生，后端开发者利器**：在终端里运行，和 Vim/tmux/git 完美配合，比 GUI 工具更适合后端开发
2. **自主 Agent，不是简单补全**：能理解项目、编辑文件、运行命令、看报错、修复，循环直到完成任务
3. **CLAUDE.md 是项目说明书**：把项目概述、技术栈、规范、常用命令写进去，Claude 不用每次问，直接上手
4. **自定义 Skills 固化工作流**：把常用流程（API 开发、bug 修复、代码审查）做成 Skill，保证一致性和质量
5. **MCP 扩展能力边界**：连接 GitHub、数据库、内部系统等 MCP Server，让 Claude 能操作外部世界
6. **任务拆分，小步迭代**：大任务拆成小步骤，每步验证，比一次丢给它靠谱
7. **人工审核是必须的**：安全、并发、事务、性能相关的代码一定要审核，不要完全信任 AI
8. **上下文管理很重要**：对话太长用 /compact，大任务开新对话，防止"失忆"

Claude Code 代表了 AI 编程的新范式——不是"AI 帮你写一行代码"，而是"AI 作为你的开发伙伴，自主完成完整任务"。用好它，开发效率能提升 2-3 倍，而且能把你从重复劳动中解放出来，专注于架构设计和业务思考。但它是工具不是替代者，你的技术判断力、业务理解、代码审美仍然是核心。
