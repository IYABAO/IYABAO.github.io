---
title: "OpenTelemetry 落地实践：从分布式追踪到全链路可观测性"
date: 2024-03-10T10:00:00+08:00
draft: false
tags: ["OpenTelemetry", "可观测性", "分布式追踪", "K8s", "Go", "微服务"]
categories: ["云原生"]
summary: "OpenTelemetry 在微服务架构中的落地实践，从分布式追踪到指标、日志的统一可观测性体系，涵盖 SDK 接入、上下文传播、采样策略、后端存储，以及踩坑经验。"
---

微服务拆分后，一个请求可能经过五六个服务，出问题时排查像破案。之前我们用 ELK 做日志、Prometheus 做指标、Jaeger 做追踪，三套系统数据不互通，排查时要来回切换。2024年初引入 OpenTelemetry，把追踪、指标、日志统一起来，今天把落地实践分享出来。

## 一、为什么选 OpenTelemetry

OpenTelemetry（简称 OTel）是 CNCF 的可观测性标准，核心优势：

1. **统一标准**：追踪、指标、日志三套信号统一规范，不用各搞一套
2. **厂商中立**：SDK 开源，后端可以换 Jaeger、Tempo、Zipkin、Datadog，不用改代码
3. **自动埋点**：Go/Java/Python 都有自动埋点库，常用框架（Gin、gRPC、GORM、Redis）自动生成 span
4. **上下文传播**：trace_id 跨服务自动传播，不用手动传参
5. **生态成熟**：CNCF 毕业项目，社区活跃，K8s 生态一等公民

## 二、架构

```text
应用服务（OTel SDK）→ OTel Collector → 后端存储
                              ↓
                    ┌───────┼───────┐
                    ↓       ↓       ↓
                Jaeger  Prometheus  Elasticsearch
                （追踪）  （指标）    （日志）
```

OTel Collector 是核心，负责接收、处理、导出可观测数据，应用只需要把数据发给 Collector，后端换什么都不用改应用。

## 三、Go 服务接入

### 安装依赖

```bash
go get go.opentelemetry.io/otel
go get go.opentelemetry.io/otel/sdk/trace
go get go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracegrpc
go get go.opentelemetry.io/contrib/instrumentation/github.com/gin-gonic/gin/otelgin
go get go.opentelemetry.io/contrib/instrumentation/google.golang.org/grpc/otelgrpc
go get go.opentelemetry.io/contrib/instrumentation/gorm.io/gorm/otelgorm
```

### 初始化 TracerProvider

```go
package main

import (
    "context"
    "go.opentelemetry.io/otel"
    "go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracegrpc"
    "go.opentelemetry.io/otel/propagation"
    "go.opentelemetry.io/otel/sdk/resource"
    sdktrace "go.opentelemetry.io/otel/sdk/trace"
    semconv "go.opentelemetry.io/otel/semconv/v1.21.0"
)

func initTracer(ctx context.Context, serviceName string) (*sdktrace.TracerProvider, error) {
    // 1. 创建 OTLP gRPC exporter，发给 Collector
    exporter, err := otlptracegrpc.New(ctx,
        otlptracegrpc.WithEndpoint("otel-collector:4317"),
        otlptracegrpc.WithInsecure(),
    )
    if err != nil {
        return nil, err
    }

    // 2. 资源信息：服务名、版本、环境
    res, err := resource.New(ctx,
        resource.WithAttributes(
            semconv.ServiceName(serviceName),
            semconv.ServiceVersion("v1.0.0"),
            semconv.DeploymentEnvironment("production"),
        ),
    )
    if err != nil {
        return nil, err
    }

    // 3. 创建 TracerProvider
    tp := sdktrace.NewTracerProvider(
        sdktrace.WithBatcher(exporter),
        sdktrace.WithResource(res),
        sdktrace.WithSampler(sdktrace.TraceIDRatioBased(0.1)), // 10% 采样
    )
    otel.SetTracerProvider(tp)

    // 4. 设置上下文传播器（W3C TraceContext）
    otel.SetTextMapPropagator(propagation.NewCompositeTextMapPropagator(
        propagation.TraceContext{},
        propagation.Baggage{},
    ))

    return tp, nil
}
```

### Gin 中间件自动埋点

```go
import "go.opentelemetry.io/contrib/instrumentation/github.com/gin-gonic/gin/otelgin"

r := gin.Default()
r.Use(otelgin.Middleware("resume-service")) // 服务名
```

加一行中间件，Gin 的每个请求自动生成 span，包含 HTTP 方法、路径、状态码、延迟。

### gRPC 拦截器

```go
import "go.opentelemetry.io/contrib/instrumentation/google.golang.org/grpc/otelgrpc"

server := grpc.NewServer(
    grpc.UnaryInterceptor(otelgrpc.UnaryServerInterceptor()),
    grpc.StreamInterceptor(otelgrpc.StreamServerInterceptor()),
)
```

### GORM 自动埋点

```go
import "go.opentelemetry.io/contrib/instrumentation/gorm.io/gorm/otelgorm"

db, err := gorm.Open(mysql.Open(dsn), &gorm.Config{})
db.Use(otelgorm.NewPlugin())
```

加完之后，每个 SQL 自动生成 span，包含 SQL 语句、执行时间、影响行数。

### 自定义 span

业务逻辑里手动加 span，追踪关键步骤：

```go
func (s *ResumeService) ParseResume(ctx context.Context, file []byte) (*Resume, error) {
    // 创建自定义 span
    ctx, span := otel.Tracer("resume-service").Start(ctx, "ParseResume")
    defer span.End()

    // 1. 解析文件
    _, span1 := otel.Tracer("resume-service").Start(ctx, "ParseFile")
    text, err := parseFile(file)
    span1.End()
    if err != nil {
        span.RecordError(err) // 记录错误
        return nil, err
    }

    // 2. AI 提取信息
    _, span2 := otel.Tracer("resume-service").Start(ctx, "AIExtract")
    resume, err := s.aiClient.Extract(text)
    span2.End()

    // 3. 存数据库（GORM 自动生成 span）
    s.db.Create(resume)

    return resume, nil
}
```

## 四、上下文传播

跨服务调用时，trace_id 自动传播：

```go
// HTTP 客户端调用其他服务
req, _ := http.NewRequest("GET", "http://other-service/api/data", nil)
// OTel 自动把 traceparent 注入请求头
otel.GetTextMapPropagator().Inject(ctx, propagation.HeaderCarrier(req.Header))
resp, err := http.DefaultClient.Do(req)
```

gRPC 客户端用拦截器自动传播：

```go
conn, _ := grpc.Dial("other-service:50051",
    grpc.WithUnaryInterceptor(otelgrpc.UnaryClientInterceptor()),
)
```

这样一个请求从网关到 A 服务到 B 服务到数据库，整条链路的 trace_id 是同一个，在 Jaeger 里能看到完整的调用链和每个环节的耗时。

## 五、采样策略

全量采样数据量太大，存储成本高。用按比例采样 + 错误全采：

```go
// 10% 正常请求采样，但错误请求 100% 采样
sampler := sdktrace.ParentBased(
    sdktrace.TraceIDRatioBased(0.1),
    sdktrace.WithRemoteParentSampled(sdktrace.AlwaysSample()),
)
```

还可以按接口设置不同采样率：

```go
// 自定义采样器：关键接口全采，普通接口10%
type customSampler struct{}

func (s customSampler) ShouldSample(p sdktrace.SamplingParameters) sdktrace.SamplingResult {
    // 从参数里取接口路径
    for _, attr := range p.Attributes {
        if attr.Key == "http.route" {
            if strings.Contains(attr.Value.AsString(), "/api/resume/parse") {
                return sdktrace.SamplingResult{Decision: sdktrace.RecordAndSample}
            }
        }
    }
    // 默认10%
    if rand.Float64() < 0.1 {
        return sdktrace.SamplingResult{Decision: sdktrace.RecordAndSample}
    }
    return sdktrace.SamplingResult{Decision: sdktrace.Drop}
}
```

## 六、OTel Collector 配置

```yaml
# otel-collector-config.yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
      http:
        endpoint: 0.0.0.0:4318

processors:
  batch:
    timeout: 5s
    send_batch_size: 1000
  memory_limiter:
    check_interval: 1s
    limit_mib: 512
  attributes:
    actions:
      - key: env
        value: production
        action: insert

exporters:
  otlp/jaeger:
    endpoint: jaeger:4317
    tls:
      insecure: true
  prometheus:
    endpoint: 0.0.0.0:8889
  elasticsearch:
    endpoints: ["http://elasticsearch:9200"]
    index: otel-logs

service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [batch, memory_limiter, attributes]
      exporters: [otlp/jaeger]
    metrics:
      receivers: [otlp]
      processors: [batch]
      exporters: [prometheus]
    logs:
      receivers: [otlp]
      processors: [batch]
      exporters: [elasticsearch]
```

Collector 做了数据接收、批量处理、内存限制、属性增强，然后分发给不同后端。应用只需要连 Collector，后端怎么换都不用改应用。

## 七、踩坑经验

1. **trace_id 不连续**：早期有些服务没接 OTel，调用链断了。必须所有服务都接，哪怕只加 HTTP 中间件也行，保证链路完整
2. **采样导致错误看不到**：10% 采样率下，错误请求可能被丢掉。改成"错误全采"，在 span 里检测到 status=error 就强制采样
3. **Collector 内存溢出**：流量大时 Collector 处理不过来，内存暴涨。加了 memory_limiter 处理器 + 批量发送，限制内存使用
4. **GORM 埋点性能损耗**：每个 SQL 都生成 span，高并发下有性能损耗。压测发现增加约 3% 延迟，可接受。对非核心接口可以关闭 GORM 埋点
5. **日志和追踪关联**：日志里要带 trace_id，才能在 ELK 里按 trace_id 搜整条链路的日志。在日志库的 hook 里从 context 取 trace_id 注入日志

## 八、效果

| 指标 | 接入前 | 接入后 |
|------|--------|--------|
| 故障排查时间 | 平均 30 分钟 | 平均 5 分钟 |
| 慢接口定位 | 靠猜，看日志 | 直接看 span 火焰图 |
| 跨服务调用链 | 看不到 | 完整可视化 |
| 错误根因定位 | 多系统切换查 | 一个 trace_id 串联所有 |

## 九、总结

OpenTelemetry 落地核心：

1. **统一标准**：追踪、指标、日志一套 SDK，不用各搞各的
2. **自动埋点优先**：Gin/gRPC/GORM/Redis 都有自动埋点，先接上覆盖 80% 场景
3. **自定义 span 补全**：关键业务逻辑手动加 span，补全调用链细节
4. **采样策略**：按比例采样 + 错误全采 + 关键接口全采，平衡成本和可见性
5. **Collector 中间层**：应用只连 Collector，后端可插拔，架构解耦
6. **日志关联**：日志里注入 trace_id，实现追踪和日志联动

可观测性是微服务架构的"眼睛"，没有它出问题就是瞎摸。OpenTelemetry 把可观测性的标准统一了，不用再在多个系统之间来回切换。建议从自动埋点开始，先把追踪链路跑通，再逐步加指标和日志，最后做告警和 dashboard，一步一步来。
