---
title: "PHP转Go实战：投递系统微服务重构的完整迁移路径"
date: 2026-04-08T10:00:00+08:00
draft: false
tags: ["PHP", "Go", "微服务", "重构", "迁移", "gRPC"]
categories: ["Go开发"]
summary: "投递系统从 PHP 单体到 Go 微服务的完整迁移实战，涵盖迁移策略、接口兼容、数据双写、灰度切换、性能对比，以及迁移过程中的踩坑与回滚经验。"
faq:
  - question: "PHP 单体怎么平滑迁移到 Go 微服务？"
    answer: "推荐\"绞杀者模式\"：第一阶段 Go 服务与 PHP 并行、只承接新功能；第二阶段按接口逐步迁移、由 Nginx 按路由分发；第三阶段数据双写保证一致性，最终完全下线 PHP。整个过程风险可控、可随时回滚。"
  - question: "迁移期间如何保证数据一致性？"
    answer: "核心是数据双写 + 校验对账：PHP 和 Go 同时写数据库，通过定时对账脚本核对差异；写流量优先收敛到 Go 侧，PHP 降级为只读从节点，避免双写冲突，从而杜绝脏读。"
  - question: "PHP 转 Go 的收益主要体现在哪里？"
    answer: "主要体现在三方面：性能（并发模型与协程让 QPS 大幅提升、延迟下降）、可维护性（强类型 + 分层架构更易扩展）、生态（K8s、gRPC、可观测性工具链更成熟）。"

---

投递系统是招聘平台的核心链路，求职者投递简历、企业查看投递、面试流程都依赖它。旧版是 PHP 单体，性能瓶颈明显。2026年4月完成了投递系统从 PHP 到 Go 微服务的迁移，今天把完整迁移路径分享出来。

## 一、迁移策略

不搞"大爆炸"式重写，用"绞杀者模式"逐步迁移：

1. **第一阶段**：Go 服务搭建，和 PHP 并行运行，Go 只做新功能
2. **第二阶段**：接口逐步从 PHP 迁移到 Go，Nginx 按接口路由
3. **第三阶段**：数据双写，PHP 和 Go 都写数据库，保证数据一致
4. **第四阶段**：灰度切换，按比例把流量从 PHP 切到 Go
5. **第五阶段**：全量切换，PHP 下线

## 二、接口兼容

Go 服务的接口返回格式和 PHP 完全一致，前端不用改：

```go
// 统一响应格式，和旧 PHP 接口一致
type Response struct {
    Code    int         `json:"code"`    // 0成功，非0失败
    Message string      `json:"message"`
    Data    interface{} `json:"data"`
}

func (h *ApplyHandler) Apply(c *gin.Context) {
    var req ApplyRequest
    c.ShouldBindJSON(&req)

    // 业务逻辑
    result, err := h.service.Apply(req.UserID, req.JobID)
    if err != nil {
        c.JSON(200, Response{Code: 1, Message: err.Error()})
        return
    }

    c.JSON(200, Response{Code: 0, Message: "success", Data: result})
}
```

Nginx 按接口路由，部分接口走 Go，部分走 PHP：

```nginx
location /api/apply/ {
    proxy_pass http://go_apply_service;
}

location /api/apply/list {
    # 这个接口还没迁移，走 PHP
    proxy_pass http://php_fpm;
}
```

## 三、数据双写

迁移期间 PHP 和 Go 都在运行，两边都要写数据库，保证数据一致：

```go
// Go 服务写入后，同步通知 PHP 更新缓存
func (s *ApplyService) Apply(userID, jobID int64) error {
    // 1. Go 写数据库
    err := s.repo.Create(&Apply{UserID: userID, JobID: jobID})
    if err != nil {
        return err
    }

    // 2. 异步通知 PHP 清缓存（双写期间）
    s.queue.Publish(&ApplyCreatedEvent{
        UserID: userID,
        JobID: jobID,
        Source: "go",
    })

    return nil
}
```

PHP 端消费事件，更新自己的缓存：

```php
// PHP 消费 Go 的投递事件
public function handleApplyCreated($event) {
    $applyId = $event['apply_id'];
    // 清 PHP 端的投递列表缓存
    $this->cache->delete("apply:list:{$event['user_id']}");
    // 如果 PHP 端也有投递记录表，同步写入
    $this->applyModel->syncFromGo($event);
}
```

## 四、灰度切换

用 Nginx 按用户 ID 哈希灰度，逐步切流量：

```nginx
# 按用户 ID 灰度，10% 走 Go
split_clients "${http_x_user_id}" $apply_backend {
    10% go_apply_service;
    *   php_fpm;
}

location /api/apply/ {
    proxy_pass http://$apply_backend;
}
```

灰度阶段观察：
- 错误率：Go 和 PHP 的接口错误率对比
- 响应时间：Go 的 P99 延迟是否比 PHP 低
- 数据一致性：两边的投递记录数量是否一致
- 用户投诉：有没有用户反馈投递异常

没问题后逐步调到 30%、50%、100%。

## 五、性能对比

| 指标 | PHP（旧） | Go（新） | 提升 |
|------|----------|---------|------|
| QPS | 800 | 5000+ | 625% |
| P99 延迟 | 120ms | 15ms | 87.5% |
| 内存占用 | 512MB/进程 | 128MB/Pod | 75% |
| 服务器数量 | 10台 | 3台 | 70% |

## 六、踩坑经验

1. **PHP 和 Go 的时间格式不一致**：PHP 返回 `Y-m-d H:i:s`，Go 默认返回 RFC3339。Go 接口统一用 `time.Format("2006-01-02 15:04:05")`，和 PHP 保持一致
2. **数据库连接池差异**：PHP-FPM 每个请求一个连接，Go 用连接池。迁移初期 Go 连接数暴增打满 MySQL。调小连接池 `SetMaxOpenConns`，加慢查询监控
3. **缓存 Key 不一致**：PHP 和 Go 的缓存 Key 命名规则不同，导致缓存不共享。统一缓存 Key 规范，用公共的 Key 生成函数
4. **灰度期间数据冲突**：同一个用户的投递请求，一部分走 PHP 一部分走 Go，可能重复投递。加了分布式锁，投递前先锁 `apply:{user_id}:{job_id}`
5. **回滚预案**：灰度出问题要能快速切回 PHP。Nginx 配置一键切换，Go 写入的数据通过双写同步回 PHP，回滚后数据不丢

## 七、总结

PHP 转 Go 迁移核心：

1. **绞杀者模式**：逐步迁移，不搞大爆炸，降低风险
2. **接口兼容**：Go 接口返回格式和 PHP 完全一致，前端不用改
3. **数据双写**：迁移期间两边都写，保证数据一致，支持回滚
4. **灰度切换**：按比例逐步切流量，每个阶段观察验证
5. **性能验证**：迁移前后做性能对比，确认 Go 的优势
6. **回滚预案**：每个阶段都有快速回滚方案，出问题不慌

从 PHP 迁移到 Go 不是"重写一遍"那么简单，接口兼容、数据双写、灰度切换、回滚预案这些工程实践才是迁移成功的关键。技术选型只是起点，落地过程中的细节处理才决定成败。
