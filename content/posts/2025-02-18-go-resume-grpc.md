---
title: "Go 简历服务接口设计：从 RESTful 到 gRPC 的跨服务通信标准"
date: 2025-02-18T10:00:00+08:00
draft: false
tags: ["Go", "gRPC", "微服务", "接口设计", "Protobuf"]
categories: ["Go开发"]
summary: "Go 简历微服务的接口设计实践，从 RESTful 到 gRPC 的演进，涵盖 Protobuf 定义、错误码规范、拦截器设计、服务注册发现，建立跨服务通信标准。"
---

简历服务从 PHP 迁移到 Go 微服务后，需要和多个服务（用户中心、职位服务、AI 服务）通信。RESTful HTTP 调用在服务间高频调用场景下性能不够，2025年2月全面切换到 gRPC，今天把接口设计实践分享出来。

## 一、为什么选 gRPC

1. **性能高**：基于 HTTP/2，二进制协议，比 RESTful JSON 快 5-10 倍
2. **强类型**：Protobuf 定义接口，编译时检查，减少运行时错误
3. **代码生成**：自动生成客户端和服务端代码，不用手写 HTTP 调用
4. **流式支持**：支持双向流，适合简历解析等长耗时任务
5. **生态成熟**：Go 生态一等公民，拦截器、负载均衡、服务发现都有现成方案

## 二、Protobuf 接口定义

```protobuf
syntax = "proto3";

package resume.v1;

option go_package = "github.com/example/api/resume/v1;v1";

service ResumeService {
  rpc GetResume(GetResumeRequest) returns (Resume);
  rpc CreateResume(CreateResumeRequest) returns (Resume);
  rpc UpdateResume(UpdateResumeRequest) returns (Resume);
  rpc DeleteResume(DeleteResumeRequest) returns (Empty);
  rpc SearchResume(SearchResumeRequest) returns (SearchResumeResponse);
  rpc ParseResume(stream ParseResumeRequest) returns (stream ParseResumeResponse); // 流式解析
}

message Resume {
  int64 id = 1;
  int64 user_id = 2;
  string name = 3;
  string phone = 4;
  string email = 5;
  repeated WorkExperience work_experiences = 6;
  repeated Education educations = 7;
  repeated string skills = 8;
  int32 status = 9;
  int64 created_at = 10;
  int64 updated_at = 11;
}

message GetResumeRequest {
  int64 id = 1;
  int64 user_id = 2; // 用于权限校验
}

message SearchResumeRequest {
  string keyword = 1;
  int32 city_id = 2;
  int32 experience_min = 3;
  int32 page = 4;
  int32 page_size = 5;
}

message SearchResumeResponse {
  repeated Resume resumes = 1;
  int32 total = 2;
}
```

## 三、错误码规范

统一错误码，不用 gRPC 默认的 code，用业务错误码：

```protobuf
message Error {
  int32 code = 1;      // 业务错误码
  string message = 2;   // 错误信息
  string request_id = 3; // 请求ID，用于排查
}
```

错误码分段：
- 0-999：通用错误（0成功，1参数错误，2未登录，3无权限，4不存在，5服务器错误）
- 1000-1999：用户服务
- 2000-2999：简历服务
- 3000-3999：职位服务

## 四、拦截器设计

gRPC 拦截器统一处理横切关注点：

```go
// 日志拦截器
func LogInterceptor(ctx context.Context, req interface{}, info *grpc.UnaryServerInfo, handler grpc.UnaryHandler) (interface{}, error) {
    start := time.Now()
    requestID := genRequestID()
    ctx = context.WithValue(ctx, "request_id", requestID)

    log.Infof("request start: %s, request_id: %s", info.FullMethod, requestID)
    resp, err := handler(ctx, req)
    log.Infof("request end: %s, cost: %dms, err: %v", info.FullMethod, time.Since(start).Milliseconds(), err)

    return resp, err
}

// 鉴权拦截器
func AuthInterceptor(ctx context.Context, req interface{}, info *grpc.UnaryServerInfo, handler grpc.UnaryHandler) (interface{}, error) {
    // 白名单接口不需要鉴权
    if isWhitelist(info.FullMethod) {
        return handler(ctx, req)
    }

    token := metadata.ValueFromIncomingContext(ctx, "authorization")
    if token == "" {
        return nil, status.Error(codes.Unauthenticated, "missing token")
    }

    userID, err := validateToken(token)
    if err != nil {
        return nil, status.Error(codes.Unauthenticated, "invalid token")
    }

    ctx = context.WithValue(ctx, "user_id", userID)
    return handler(ctx, req)
}
```

## 五、服务注册发现

用 etcd 做服务注册发现：

```go
// 服务注册
func RegisterService(etcdAddr string, serviceName string, addr string) error {
    cli, _ := clientv3.New(clientv3.Config{Endpoints: []string{etcdAddr}})
    lease, _ := cli.Grant(context.Background(), 5) // 5秒租约
    key := fmt.Sprintf("/services/%s/%s", serviceName, addr)
    cli.Put(context.Background(), key, addr, clientv3.WithLease(lease.ID))

    // 保持租约
    ch, _ := cli.KeepAlive(context.Background(), lease.ID)
    go func() {
        for range ch {}
    }()
    return nil
}

// 服务发现 + 客户端负载均衡
func NewClient(etcdAddr string, serviceName string) (resume.ResumeServiceClient, error) {
    r := etcd.NewResolver(etcdAddr, serviceName)
    conn, _ := grpc.Dial(
        "etcd:///"+serviceName,
        grpc.WithResolvers(r),
        grpc.WithDefaultServiceConfig(`{"loadBalancingPolicy":"round_robin"}`),
        grpc.WithTransportCredentials(insecure.NewCredentials()),
    )
    return resume.NewResumeServiceClient(conn), nil
}
```

## 六、踩坑经验

1. **Protobuf 字段编号不能改**：字段编号是序列化的标识，改了会导致旧客户端解析失败。废弃字段要保留编号，不能复用
2. **大消息性能问题**：简历详情包含工作经历、教育经历等，消息体大时 gRPC 性能下降。用分页或按需加载，不要一次返回所有字段
3. **超时设置**：gRPC 默认没有超时，要手动设置 context 超时，防止服务 hang 住
4. **错误信息不要泄露内部细节**：返回给客户端的错误信息要简洁，内部错误详情记日志

## 七、总结

Go 微服务 gRPC 接口设计核心：

1. **Protobuf 定义接口**：强类型、代码生成、编译时检查
2. **统一错误码**：业务错误码分段，不依赖 gRPC 默认 code
3. **拦截器处理横切**：日志、鉴权、限流、监控都用拦截器统一处理
4. **服务注册发现**：etcd + 客户端负载均衡，服务上下线自动感知
5. **流式接口**：长耗时任务用流式通信，支持进度反馈
6. **兼容性设计**：字段编号不能改，废弃字段保留，新增字段用默认值

gRPC 适合服务间高频调用场景，性能和类型安全都比 RESTful 好。但对外 API（前端调用）还是建议用 RESTful，gRPC 主要用于内部服务间通信。技术选型要根据场景，不是所有接口都要用 gRPC。
