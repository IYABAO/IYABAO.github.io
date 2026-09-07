---
title: "gRPC 服务间通信标准：我们是怎么定的"
date: 2023-01-10T09:00:00+08:00
lastmod: 2023-01-10T09:00:00+08:00
draft: false
author: IYABAO
tags:
  - Go
  - gRPC
  - Protobuf
  - 微服务
categories:
  - 技术
summary: "微服务拆出来第一件事不是写代码，是定通信标准。proto 目录结构、错误码、trace、鉴权、兼容性规范，这一套标准定了，后面 20 个服务才没乱。"
---

# gRPC 服务间通信标准：我们是怎么定的

从 PHP 单体拆 Go 微服务，第一个月最乱的不是代码，是**服务之间怎么说话**。A 服务调 B 服务，错误码各写各的、trace 对不上、字段命名风格混乱。后来我们停下来，花一周定了一套 gRPC 通信标准，从此 20 个服务的联调成本直线下降。

## 一、proto 的组织

### 目录结构

```
proto/
├── common/          # 公共类型（分页、错误、元数据）
│   ├── page.proto
│   └── error.proto
├── resume/          # 按领域分目录
│   ├── resume_service.proto
│   └── resume_model.proto
└── delivery/
    └── delivery_service.proto
```

**规则**：`<领域>/<服务>_service.proto` 放 service 定义，`<领域>_model.proto` 放消息模型。公共类型绝对不允许各服务自己复制一份——那会造成跨服务类型不兼容。

### package 与 go_package 命名

```proto
syntax = "proto3";
package plbear.resume.v1;
option go_package = "github.com/yourorg/proto-gen/go/resume/v1;resumev1";
```

**版本进 package**：`v1` 进 package 名，破坏性变更直接升 `v2`，新旧共存，不用改服务代码。这是我们踩坑后加的规定——早期没版本，改个字段全链路要一起发版。

## 二、错误码规范（最重要的标准）

gRPC 原生 status code 只有 16 个，业务错误必须自定义。我们定：

```
标准结构：
{ code: "RESUME_NOT_FOUND", message: "简历不存在", http_status: 404 }
```

| 层级 | 例子 |
|---|---|
| 框架错误（gRPC code） | INVALID_ARGUMENT / NOT_FOUND / INTERNAL |
| 领域错误（自定义 code） | RESUME_NOT_FOUND / DELIVERY_DUPLICATED / QUOTA_EXCEEDED |
| 细节（details） | 错误字段、重试提示 |

**核心原则**：

1. **错误码全局唯一**：全公司一个错误码注册表（proto 文件 + 文档），不允许各服务自造
2. **code 稳定，message 可变**：code 是给程序判断的（永不改），message 是给用户看的（可改文案）
3. **错误码带上域前缀**：`RESUME_` / `DELIVERY_`，一眼看出是哪个服务

## 三、trace 与元数据传递

服务间调用必须透传 trace：

```go
// 拦截器里从 metadata 取 trace id，不存在则生成
md, ok := metadata.FromIncomingContext(ctx)
traceID := firstNonEmpty(md.Get("x-trace-id"), newTraceID())
ctx = context.WithValue(ctx, traceIDKey{}, traceID)
// 出站时自动附加
grpc.SetHeader(ctx, metadata.Pairs("x-trace-id", traceID))
```

**规则**：入站拦截器**取不到就生成**，出站拦截器**必有就附加**。这样不管调用链多深，日志里 `x-trace-id` 一定存在——排查问题全靠它。

其他元数据统一走 `x-` 前缀：`x-user-id`（当前用户）、`x-tenant-id`（租户）、`x-source`（调用来源）。**业务参数绝不放进 metadata**，那会让审计和序列化都变脏。

## 四、鉴权与超时

- **内部鉴权**：服务间用 mTLS + service token（Header 里 `authorization: Bearer <service-token>`），网关层校验
- **用户鉴权**：网关解析用户态后放 `x-user-id`，下游服务信任该字段（内网可信）
- **超时规范**：每个 RPC 必须显式设超时（默认 3s，写操作 5s），**禁止无超时调用**——这是死锁和 goroutine 泄漏的最大来源

## 五、兼容性红线

1. **字段只增不减**：改 proto 只能加字段（`optional` 或 `repeated`），不能删、不能改类型、不能改编号
2. **枚举只增不减**：枚举值不允许复用已删除的编号
3. **语义不变**：字段含义不能变（比如 `status` 从"审核状态"改成"投递状态"是破坏性变更）
4. **接口冻结走评审**：service 接口变更（方法签名）必须评审，非必须不破坏

配合 buf 的 breaking 检查进 CI：**proto 变更触发破坏性检查，不过不能合代码**。

## 六、落地效果

- 联调耗时从"周级"降到"天级"：错误码对得上、trace 找得到、类型不打架
- 新人上手成本大降：照标准写，不会错
- 20 个服务的通信零协议事故

## 总结

微服务的通信标准，定的不是 API 格式，是**团队协作的契约**：

1. proto 版本进 package，破坏性变更升版本
2. 错误码全局注册、code 稳定 message 可变
3. trace 透传是硬约束，取不到就生成
4. 兼容性红线靠 CI 强制，不靠自觉

**先定标准再写代码，比写完再对齐便宜十倍。**
