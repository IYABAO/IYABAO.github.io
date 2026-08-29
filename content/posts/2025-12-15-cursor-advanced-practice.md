---
title: "Cursor 进阶实战：Rules 文件、Composer 模式与大型重构技巧"
date: 2025-12-15T14:00:00+08:00
draft: false
tags: ["Cursor", "AI编程", "Rules", "Composer", "代码重构", "研发效能"]
categories: ["工程效能"]
summary: "Cursor AI 编辑器的进阶使用技巧，涵盖 .cursorrules 项目规则配置、Composer 多文件编辑模式、@ 引用系统、自定义指令、大型重构工作流，以及在 Go/PHP 微服务项目中的实战经验和效率提升数据。"
keywords: ["Cursor", "Rules", "Composer", "重构", "AI编程"]
---

Cursor 是目前最火的 AI 原生编辑器，很多人用 Cursor 只是把它当"带 AI 补全的 VS Code"，其实 Cursor 的高级功能（Rules、Composer、@ 引用）能让开发效率再提升一个量级。我用 Cursor 做了几个微服务重构项目，总结了一套进阶使用方法。今天把实战技巧分享出来。

## 一、Cursor 核心功能回顾

Cursor 基于 VS Code fork，核心 AI 功能：

| 功能 | 说明 | 快捷键 |
|------|------|--------|
| Tab 补全 | 行内 AI 代码补全 | 自动触发，Tab 接受 |
| Chat | 侧边栏 AI 对话，问答和代码生成 | Ctrl+L |
| Composer | 多文件编辑模式，AI 自主编辑多个文件 | Ctrl+I |
| @ 引用 | 引用文件、文件夹、代码符号、网页、文档 | 输入 @ 触发 |
| Rules | 项目级/全局规则，AI 遵循的规范 | .cursorrules 文件 |
| Agent 模式 | Chat 里的 Agent 模式，自主规划和执行 | Chat 里切换 |

很多人只用 Tab 补全和简单 Chat，这只用了 Cursor 30% 的能力。Composer + Rules + @ 引用才是 Cursor 的真正威力。

## 二、.cursorrules 项目规则

.cursorrules 是 Cursor 的项目级配置文件，放在项目根目录，AI 会自动读取并遵循。这是让 AI 输出符合项目规范的关键。

### 基础配置

```markdown
# .cursorrules

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
- 测试：testify + mockery

## 代码规范
- 分层架构：handler → service → repository，不跨层调用
- 错误处理：用自定义 error 类型，统一返回 {code, message, data}
- 参数校验：用 go-playground/validator，在 handler 层校验
- 日志：用 zap，结构化日志，包含 request_id、user_id
- 命名：函数名驼峰，常量全大写下划线分隔，包名小写
- 注释：导出函数必须有注释，复杂逻辑要有行内注释
- 测试：核心逻辑必须有单测，覆盖率 80% 以上

## 常用命令
- 构建：make build
- 测试：make test
- 运行：make run
- 代码生成：make gen（mock、swagger）
- Lint：make lint

## 注意事项
- 不要直接修改 main 分支，新建分支开发
- 数据库迁移用 golang-migrate，不要手动改表
- 敏感配置不要硬编码，从环境变量读
- 提交前跑 make lint 和 make test
- 不要引入新的依赖，除非确有必要且经过评审
```

### 分目录 Rules

Cursor 支持在子目录放 .cursorrules，会和根目录的规则合并，子目录的规则优先级更高：

```text
project/
├── .cursorrules              # 全局规则
├── handler/
│   └── .cursorrules          # handler 层专属规则
├── service/
│   └── .cursorrules          # service 层专属规则
└── repository/
    └── .cursorrules          # repository 层专属规则
```

handler 层的 .cursorrules：

```markdown
## Handler 层规范
- 只做参数校验、调用 service、格式化响应，不包含业务逻辑
- 参数校验用 validator，校验失败返回 400，code=1
- 成功返回 200，code=0
- 必须从 context 取 request_id 和 user_id，注入日志
- 不直接操作数据库，不直接调用其他服务
- 每个 handler 函数必须有对应的测试
```

### 全局 Rules

除了项目级 .cursorrules，还可以配置全局规则（Cursor Settings → Rules），适用于所有项目：

```markdown
## 全局编码规范
- 代码简洁优先，不要过度设计
- 变量命名要有意义，不要用 a、b、tmp 这种无意义名字
- 函数不要太长，超过 50 行考虑拆分
- 注释为什么这么做，而不是做了什么
- 不要重复造轮子，优先用标准库或已有工具
- 安全第一，注意 SQL 注入、XSS、权限校验
```

### Rules 的效果

配置了 .cursorrules 后，AI 生成的代码：
- 自动遵循项目的分层架构，不会在 handler 里写业务逻辑
- 自动用项目指定的库（zap、validator、testify），不会引入新依赖
- 自动遵循命名规范和代码风格
- 自动生成符合项目规范的错误处理和返回格式
- 自动知道常用命令，不用每次告诉它怎么构建测试

没有 Rules 的时候，AI 生成的代码可能用 fmt.Println 而不是 zap，可能用 net/http 而不是 Gin，可能不遵循分层架构。有了 Rules，AI 输出的代码质量和一致性大幅提升。

## 三、@ 引用系统

@ 引用是 Cursor 最强大的功能之一，能让 AI 精准获取上下文。

### 引用类型

| 引用 | 语法 | 说明 |
|------|------|------|
| 文件 | @filename | 引用整个文件内容 |
| 文件夹 | @dirname/ | 引用文件夹下所有文件 |
| 代码符号 | @symbol | 引用函数/类/变量定义 |
| 代码库 | @code | 引用整个代码库（搜索相关代码） |
| 网页 | @url | 引用网页内容 |
| 文档 | @docs | 引用库/框架的官方文档 |
| Git | @git | 引用 git 历史、diff、PR |

### 实战用法

**引用文件**：
```text
参考 @/internal/handler/resume.go 的风格，给 job-service 加类似的接口
```

Cursor 会读取 resume.go 的内容，模仿它的风格写新代码。

**引用文件夹**：
```text
看一下 @/internal/service/ 目录下的代码，总结 service 层的设计模式，然后给 apply-service 加 service 层
```

**引用代码符号**：
```text
@GetResume 这个函数有性能问题，帮我优化一下
```

直接引用函数，Cursor 会定位到函数定义并分析。

**引用整个代码库**：
```text
@code 我们项目里的错误处理是怎么做的？给我几个例子
```

@code 会搜索整个代码库，找到相关的代码片段。

**引用文档**：
```text
@docs gin 怎么写中间件？给我一个鉴权中间件的例子
```

@docs 会搜索 Gin 的官方文档，给出准确的用法，不会瞎编 API。

**引用 Git diff**：
```text
@gd （git diff 的缩写）看一下当前改动，帮我做 code review
```

@gd 引用当前未提交的改动，AI 帮你做代码审查。

### @ 引用的技巧

1. **精准引用比泛泛而谈好**：不要说"参考项目风格"，要说"参考 @/internal/handler/resume.go 的风格"
2. **多个引用组合用**："参考 @resume.go 的风格，用 @gin 文档的中间件写法，给 @job-service 加鉴权"
3. **大文件不要全引用**：大文件全引用会占用太多上下文，用 @符号 引用具体函数，或告诉 AI "只看这个文件的 handler 函数部分"
4. **@code 搜索要给关键词**："@code 错误处理"比 "@code 看看项目" 效果好
5. **引用文档避免幻觉**：涉及第三方库 API 时，用 @docs 引用官方文档，AI 不会瞎编不存在的 API

## 四、Composer 多文件编辑

Composer 是 Cursor 的杀手级功能，能让 AI 自主编辑多个文件，完成复杂任务。

### 启动 Composer

- 快捷键：Ctrl+I（Mac: Cmd+I）
- 或在 Chat 里切换到 Composer 模式

Composer 界面：
- 上方是任务描述输入框
- 中间是 AI 规划的步骤和编辑的文件
- 下方是 Accept/Reject 按钮，逐个文件确认修改

### Composer 工作流

**步骤1：描述任务**

要详细、具体，包含：
- 要做什么
- 涉及哪些文件/模块
- 有什么约束和要求
- 期望的结果

```text
给 resume-service 加一个批量导出接口：
1. 接口 POST /api/resume/export，接收筛选条件（keyword、city、experience）
2. 异步处理：接口立即返回任务ID，后台 goroutine 生成 Excel
3. 查询任务状态接口 GET /api/resume/export/{task_id}
4. 任务状态存在 Redis，任务记录存在 MySQL
5. Excel 生成用 excelize 库
6. 完成后发通知（调用 notification-service）
7. 加单测，覆盖正常和异常场景

先看一下现有代码结构，确认方案后再开始改。
```

**步骤2：AI 规划**

Composer 会先分析任务，列出要修改/创建的文件：
- 创建 internal/types/export.go（请求/响应类型）
- 修改 internal/handler/resume.go（加 handler）
- 创建 internal/service/export.go（业务逻辑）
- 创建 internal/repository/export_task.go（任务持久化）
- 修改 internal/router/router.go（注册路由）
- 创建 internal/service/export_test.go（单测）

可以让 AI 先展示计划，确认后再执行。

**步骤3：AI 执行编辑**

AI 逐个文件编辑，每个文件的修改都会展示 diff，可以：
- Accept：接受这个文件的修改
- Reject：拒绝这个文件的修改
- 修改后再接受：手动调整 AI 的修改

**步骤4：验证**

所有文件修改完后，运行构建和测试验证：
```
make build
make test
```

如果有报错，把报错贴给 Composer，让它自动修复。

### Composer 高级技巧

**1. 分批处理大任务**

不要一次让 Composer 改 20 个文件，上下文会不够，质量会下降。拆成小任务：
- 第一批：加数据模型和 repository 层
- 第二批：加 service 层
- 第三批：加 handler 和路由
- 第四批：加测试

每批 3-5 个文件，质量更高。

**2. 先让 AI 读代码再改**

复杂任务先让 AI 读相关代码，理解现有架构和风格，再开始改：
```text
先看一下 @/internal/service/ 和 @/internal/repository/ 目录下的代码，
总结一下现有的设计模式和代码风格，然后再开始实现批量导出功能。
```

**3. 用 @ 引用指定文件**

任务描述里用 @ 引用相关文件，AI 不用自己找，更精准：
```text
参考 @/internal/handler/resume.go 的风格，
参考 @/internal/service/resume.go 的错误处理方式，
给 job-service 加类似的接口。
```

**4. 明确约束条件**

告诉 AI 不能做什么，避免它"自由发挥"：
```text
约束：
- 不要引入新的依赖，用现有的库
- 不要修改现有的函数签名，只加新函数
- 数据库操作必须用事务
- 不要在 handler 层写业务逻辑
```

**5. 增量验证**

每改完一批文件就跑构建测试，有问题立即修复，不要攒到最后一起改。早期发现的问题更容易修复。

### Composer vs Chat

| 维度 | Chat | Composer |
|------|------|----------|
| 适用场景 | 问答、单文件修改、解释代码 | 多文件编辑、复杂功能开发、重构 |
| 文件编辑 | 一次一个，需要复制粘贴 | 自主编辑多个文件，diff 展示 |
| 上下文 | 手动 @ 引用 | 自动搜索和引用相关文件 |
| 可控性 | 高（每次输出都要确认） | 中（AI 自主编辑，需要逐个文件确认） |
| 适合任务大小 | 小（单文件/小功能） | 大（多文件/复杂功能） |

简单任务用 Chat，复杂多文件任务用 Composer。

## 五、大型重构工作流

用 Cursor 做大型重构（如微服务拆分、框架迁移、架构升级），有一套成熟的工作流。

### 案例：从 PHP 迁移到 Go

任务：把 apply-service 从 PHP 迁移到 Go，涉及 10+ 个文件。

**阶段1：理解和规划（Chat 模式）**

1. 让 AI 读 PHP 版代码，理解业务逻辑
2. 让 AI 输出迁移方案（目录结构、接口定义、数据模型）
3. 人工审核方案，确认后进入实施

**阶段2：搭建骨架（Composer）**

1. 创建 Go 项目目录结构
2. 定义接口和数据模型（types 包）
3. 搭建 handler/service/repository 空骨架
4. 配置依赖、Makefile、Dockerfile

**阶段3：逐模块迁移（Composer，分批）**

每批迁移一个模块：
1. 第一批：用户认证模块（3个文件）
2. 第二批：职位查询模块（4个文件）
3. 第三批：投递管理模块（5个文件）
4. 第四批：统计报表模块（3个文件）

每批：
- 用 Composer 生成代码
- 人工 review 每个文件
- 跑单测验证
- 跑集成测试验证

**阶段4：集成和测试（Chat + 手动）**

1. 整合所有模块，跑全量测试
2. 用 Chat 排查和修复 bug
3. 性能测试，对比 PHP 版性能
4. 写迁移文档和回滚方案

**阶段5：灰度上线（手动 + Chat）**

1. 部署到预发布环境，和 PHP 版双跑
2. 按比例切流量，对比两个版本的结果
3. 全量切换，观察一周
4. 下线 PHP 版

### 重构的注意事项

1. **不要让 AI 一次改太多**：大型重构拆成小步骤，每步可验证、可回滚
2. **人工 review 不能省**：AI 生成的代码可能有逻辑错误，特别是业务逻辑，必须人工 review
3. **测试是安全网**：重构前先有测试，重构后跑测试，确保行为一致。没有测试的代码先补测试再重构
4. **保留旧代码**：重构期间新旧代码并存，灰度切换，不要一上来就删旧代码
5. **用 AI 做重复劳动**：重复的模式化代码（CRUD、DTO 转换、错误处理）让 AI 做，人专注于架构设计和业务逻辑
6. **用 @ 引用保持一致性**：每批都引用之前写好的文件，保持风格和模式一致

## 六、效率提升数据

我们团队用 Cursor 进阶功能（Rules + Composer + @ 引用）后，效率提升明显：

| 任务类型 | 不用 Cursor | 用 Cursor（基础） | 用 Cursor（进阶） | 提升 |
|---------|-----------|-----------------|-----------------|------|
| 新建 CRUD 接口 | 2小时 | 1小时 | 20分钟 | 6倍 |
| 单文件 bug 修复 | 30分钟 | 15分钟 | 5分钟 | 6倍 |
| 多文件新功能开发 | 1天 | 4小时 | 1.5小时 | 5倍 |
| 代码重构（10文件） | 3天 | 1.5天 | 6小时 | 4倍 |
| 写单测 | 4小时 | 2小时 | 40分钟 | 6倍 |
| Code Review | 1小时 | 30分钟 | 10分钟 | 6倍 |

平均开发效率提升 4-6 倍，而且代码质量更一致（因为有 Rules 约束）。

## 七、踩坑经验

1. **Composer 会"幻觉"文件**：Composer 有时会引用不存在的文件或函数，特别是大型项目。要逐个文件确认，不要全 Accept
2. **上下文窗口限制**：项目太大时，@code 引用整个代码库会超出上下文窗口。用精准的 @文件 和 @符号 引用，不要用 @code 搜整个库
3. **Rules 太长会被忽略**：.cursorrules 写太长，AI 可能只关注前面的部分。保持简洁，重点规则放前面，分目录写专属规则
4. **Composer 改坏现有代码**：Composer 有时会"顺手"修改不相关的代码，导致 bug。每个文件的 diff 要仔细看，特别是不应该被修改的文件
5. **AI 生成的测试可能"放水"**：AI 写的单测有时断言太松或 mock 不对，测试通过但实际没验证逻辑。测试代码也要人工 review
6. **不要完全依赖 AI**：架构设计、业务逻辑、安全相关的代码，AI 只能做参考，最终决策和 review 要人来做
7. **敏感信息不要输入**：不要把 API Key、密码、客户数据贴到 Chat 里，虽然 Cursor 有隐私模式，但还是要小心
8. **Cursor 也会犯错**：AI 会生成有 bug 的代码，特别是复杂逻辑。不要"AI 写的就一定对"，要验证、要测试、要 review

## 八、总结

Cursor 进阶使用核心：

1. **.cursorrules 是项目灵魂**：配置项目规范、技术栈、代码风格、常用命令，AI 输出质量和一致性大幅提升
2. **@ 引用是精准制导**：引用文件、符号、文档、代码库，给 AI 精准上下文，比泛泛而谈效果好 10 倍
3. **Composer 是多文件利器**：复杂功能开发、大型重构，Composer 自主编辑多个文件，比 Chat 复制粘贴高效得多
4. **任务拆分是关键**：大任务拆成小批次（3-5个文件），每批验证，质量更高，风险更小
5. **人工 review 不能省**：AI 生成的代码可能有逻辑错误，特别是业务逻辑和安全相关，必须人工 review
6. **测试是安全网**：AI 写代码快，但也要有测试验证，重构前先补测试，重构后跑测试
7. **效率提升 4-6 倍**：用好进阶功能，平均开发效率提升 4-6 倍，代码质量更一致
8. **AI 是助手不是替代**：架构设计、业务决策、安全审查要人来做，AI 做重复劳动和辅助分析

Cursor 代表了 AI 编程的新范式——不是"AI 帮你写一行代码"，而是"AI 作为你的编程伙伴，理解项目、遵循规范、自主完成复杂任务"。用好 Rules、Composer、@ 引用这三大利器，Cursor 才能从"高级补全工具"变成"真正的 AI 编程伙伴"。但记住，AI 越强，人的判断力越重要——AI 负责"做"，人负责"决策"和"审查"。
