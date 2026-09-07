---
title: "gRPC 网关与 BFF：前后端解耦的正确姿势"
date: 2021-02-02T09:00:00+08:00
lastmod: 2021-02-02T09:00:00+08:00
draft: false
author: IYABAO
tags:
  - gRPC
  - BFF
  - 架构
categories:
  - 技术
summary: "内部 gRPC 服务怎么给外部提供 API？BFF 聚合、网关转发、协议转换——gRPC 网关与 BFF 模式的架构设计与实践。"
---

# gRPC 网关与 BFF：前后端解耦的正确姿势

微服务内部用 gRPC（高效、强类型），但前端要的是 REST/JSON。中间这层怎么设计？**BFF（Backend For Frontend）** 和 **网关** 是两种答案。这篇文章是我们在 gRPC 微服务化后的对外接口层设计。

## 一、问题：内部 gRPC，外部要 REST

```
微服务 A（gRPC）  ─┐
微服务 B（gRPC）  ─┼── 前端要什么？→ JSON API（REST）
微服务 C（gRPC）  ─┘     还要：聚合、裁剪、鉴权、限流

直接暴露 gRPC？
  ❌ 前端生态对 gRPC 支持差（浏览器不原生支持）
  ❌ 内部接口太细（前端要 1 个页面，gRPC 要调 8 个）
  ❌ 内部数据结构暴露（耦合、改内部就改前端）
```

## 二、两种模式

### 模式 A：网关（统一入口）

```
前端 → REST API → 网关 → gRPC 微服务
                        ├─ 路由、鉴权、限流
                        ├─ 协议转换（REST ↔ gRPC）
                        └─ 聚合（可选，简单聚合）
```

**适用**：对外统一入口、跨服务路由、通用横切（鉴权/限流/审计）。

### 模式 B：BFF（前端专属后端）

```
Web 前端 → BFF-Web → gRPC 微服务
App 前端 → BFF-App → gRPC 微服务
                     ├─ 聚合（按前端页面组装）
                     ├─ 裁剪（只给前端要的字段）
                     └─ 适配（前端特殊逻辑）
```

**适用**：多端（Web/App/小程序）差异大、页面级聚合多、前端体验定制。

## 三、我的实践：网关 + BFF 分层

```
前端 → REST → 网关（路由/鉴权/限流/审计）→ BFF（聚合/裁剪）→ gRPC 服务
```

**为什么两层都要**：

```
网关管"横切"（所有接口统一的：鉴权、限流、审计、版本）
BFF 管"业务"（页面级聚合、字段裁剪、前端适配）

单网关：聚合逻辑堆在网关 → 网关变成"上帝服务"
单 BFF：鉴权限流每端各做一遍 → 重复
```

## 四、BFF 的落地

### gRPC 网关生成（协议转换）

```proto
// proto 定义 REST 映射（grpc-gateway 注解）
service ResumeService {
  rpc GetResume(GetResumeReq) returns (Resume) {
    option (google.api.http) = {
      get: "/v1/resumes/{id}"
    };
  }
}
// 生成：HTTP 处理器 → 转 gRPC 调用（自动完成 REST↔gRPC）
```

### BFF 聚合

```go
// BFF：一次前端调用，聚合多个 gRPC 服务
func GetProfilePage(ctx, req) (*ProfileVO, error) {
    // 并行调三个服务
    resume, _ := resumeClient.GetResume(ctx, req)
    apply, _ := applyClient.GetApplications(ctx, req.UserId)
    view, _ := statClient.GetProfileViews(ctx, req.UserId)
    // 组装前端要的结构（裁剪字段）
    return &ProfileVO{
        Resume: resume,
        ApplyCount: len(apply),
        Views: view.Count,
    }, nil
}
```

**关键**：

```
✅ 并行聚合（gRPC 并发调用，不等串行）
✅ 裁剪字段（只返回前端要的，减少传输）
✅ BFF 无业务逻辑（只是聚合+适配，别在 BFF 写业务）
✅ 错误包装（服务错误 → 前端友好错误码）
```

## 五、踩坑记录

1. **BFF 变成业务层**：聚合逻辑越写越多，最后 BFF 重写了业务 → BFF 只做"组装和裁剪"，业务在服务层
2. **聚合串行**：3 个 gRPC 调用串行，页面延迟 = 3 倍 → 并行 + 超时控制（总超时 500ms）
3. **网关鉴权重复**：网关鉴权了，BFF 又鉴权 → 双层鉴权（网关验 token，BFF 验上下文，职责不同）
4. **gRPC 错误映射**：gRPC status 直接透传给前端（看不懂）→ 映射为 HTTP 状态码 + 业务错误码

## 六、什么时候不需要 BFF

```
✅ 单端（只有一个 Web）：网关 + 直接 gRPC 网关映射就够
✅ 接口简单（CRUD 直接映射）：不需要聚合
✅ 团队小：BFF 是额外维护成本

需要 BFF 的信号：
  ❌ 前端要的"页面数据"要调 3+ 个服务
  ❌ 多端（Web/App）返回结构不同
  ❌ 前端频繁催"能不能给个聚合接口"
```

## 总结

gRPC 网关与 BFF 的核心认知：

1. **网关管横切**（鉴权/限流/审计），**BFF 管聚合**（页面组装/裁剪）
2. **gRPC 网关自动转换协议**：proto 注解生成 REST 映射
3. **BFF 是"薄层"**：只组装裁剪，别写业务
4. **按需引入**：单端简单接口不需要 BFF

**对外接口层是微服务的"门面"**：网关+BFF 分层，让内部 gRPC 随便演进，前端 API 稳定不变——解耦的价值就在这里。
