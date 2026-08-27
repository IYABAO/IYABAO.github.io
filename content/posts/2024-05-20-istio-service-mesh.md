---
title: "Service Mesh Istio 实战：微服务流量治理与灰度发布"
date: 2024-05-20T14:00:00+08:00
draft: false
tags: ["Istio", "Service Mesh", "微服务", "K8s", "灰度发布", "流量治理"]
categories: ["云原生"]
summary: "Istio Service Mesh 在微服务架构中的落地实践，涵盖流量治理、灰度发布、熔断限流、可观测性，以及从侵入式 SDK 到无侵入 Sidecar 的演进经验。"
---

微服务多了之后，流量治理是个头疼事——灰度发布要改 Nginx 配置、熔断限流要在每个服务里写代码、调用链追踪要每个服务接 SDK。2024年中我们引入了 Istio Service Mesh，把这些能力从业务代码里抽出来，放到 Sidecar 代理里统一管理。今天把实战经验分享出来。

## 一、为什么需要 Service Mesh

之前的流量治理方案：

1. **灰度发布**：Nginx 按比例分流，每次灰度要改 Nginx 配置，reload 有风险
2. **熔断限流**：每个服务引入 hystrix-go 或 sentinel，代码侵入，配置不统一
3. **服务间鉴权**：每个服务自己验 Token，重复实现
4. **调用链追踪**：每个服务接 OTel SDK，升级要改所有服务
5. **mTLS**：服务间通信加密，自己搞证书管理很麻烦

这些都是"横切关注点"，跟业务逻辑无关，但每个服务都要搞一遍。Service Mesh 的核心思想就是把这些能力下沉到基础设施层，业务服务无感知。

## 二、Istio 架构

```
┌─────────────────────────────────────────┐
│              Istio 控制面                 │
│  istiod（配置下发 + 证书管理 + 可观测）    │
└──────────────────┬──────────────────────┘
                   │ xDS 协议下发配置
┌──────────────────▼──────────────────────┐
│              数据面（Pod）                 │
│  ┌──────────┐    ┌──────────────────┐   │
│  │ 业务容器  │◄──►│ Envoy Sidecar   │   │
│  │          │    │ （流量代理）       │   │
│  └──────────┘    └──────────────────┘   │
└─────────────────────────────────────────┘
```

- **控制面 istiod**：管理配置、证书、可观测性数据，通过 xDS 协议把配置下发给所有 Sidecar
- **数据面 Envoy**：每个 Pod 里注入一个 Envoy Sidecar，所有进出 Pod 的流量都经过它，业务容器无感知

## 三、灰度发布

Istio 的 VirtualService + DestinationRule 实现精细化流量控制。

### 按比例灰度

简历服务 v2 上线，先切 10% 流量：

```yaml
# DestinationRule：定义版本子集
apiVersion: networking.istio.io/v1beta1
kind: DestinationRule
metadata:
  name: resume-service
spec:
  host: resume-service
  subsets:
    - name: v1
      labels:
        version: v1
    - name: v2
      labels:
        version: v2
---
# VirtualService：流量分配
apiVersion: networking.istio.io/v1beta1
kind: VirtualService
metadata:
  name: resume-service
spec:
  hosts:
    - resume-service
  http:
    - route:
        - destination:
            host: resume-service
            subset: v1
          weight: 90
        - destination:
            host: resume-service
            subset: v2
          weight: 10
```

改 weight 就能调整流量比例，不用改服务代码，不用 reload Nginx，秒级生效。观察没问题后逐步调到 30%、50%、100%。

### 按用户特征灰度

只让内部员工或特定用户走 v2：

```yaml
apiVersion: networking.istio.io/v1beta1
kind: VirtualService
metadata:
  name: resume-service
spec:
  hosts:
    - resume-service
  http:
    - match:
        - headers:
            x-user-type:
              exact: internal  # 内部员工
      route:
        - destination:
            host: resume-service
            subset: v2
    - route:
        - destination:
            host: resume-service
            subset: v1
```

请求头里带 `x-user-type: internal` 的走 v2，其他走 v1。还可以按 cookie、URL 参数、来源 IP 匹配。

## 四、熔断与限流

### 熔断

DestinationRule 里配置连接池和异常点检测：

```yaml
apiVersion: networking.istio.io/v1beta1
kind: DestinationRule
metadata:
  name: resume-service
spec:
  host: resume-service
  trafficPolicy:
    connectionPool:
      tcp:
        maxConnections: 100        # 最大连接数
      http:
        http1MaxPendingRequests: 50 # 最大等待请求数
        maxRequestsPerConnection: 10
    outlierDetection:
      consecutive5xxErrors: 5       # 连续5次5xx错误
      interval: 30s                  # 检测间隔
      baseEjectionTime: 60s          # 剔除时间60秒
      maxEjectionPercent: 50         # 最多剔除50%的实例
```

某个实例连续5次返回5xx，自动被剔除60秒，流量不打给它，60秒后自动恢复。不用在代码里写熔断逻辑。

### 限流

用 EnvoyFilter 配置本地限流：

```yaml
apiVersion: networking.istio.io/v1alpha3
kind: EnvoyFilter
metadata:
  name: resume-service-ratelimit
spec:
  workloadSelector:
    labels:
      app: resume-service
  configPatches:
    - applyTo: HTTP_FILTER
      match:
        context: SIDECAR_INBOUND
      patch:
        operation: INSERT_BEFORE
        value:
          name: envoy.filters.http.local_ratelimit
          typed_config:
            "@type": type.googleapis.com/envoy.extensions.filters.http.local_ratelimit.v3.LocalRateLimit
            stat_prefix: http_local_rate_limiter
            token_bucket:
              max_tokens: 100
              tokens_per_fill: 100
              fill_interval: 1s
            filter_enabled:
              runtime_key: local_rate_limit_enabled
              default_value:
                numerator: 100
                denominator: HUNDRED
            filter_enforced:
              runtime_key: local_rate_limit_enforced
              default_value:
                numerator: 100
                denominator: HUNDRED
```

每秒最多100个请求，超过返回429。配置在 Sidecar 里，业务服务无感知。

## 五、mTLS 服务间加密

Istio 默认开启服务间 mTLS，所有服务间通信自动加密：

```yaml
apiVersion: security.istio.io/v1beta1
kind: PeerAuthentication
metadata:
  name: default
  namespace: default
spec:
  mtls:
    mode: STRICT  # 严格模式，只接受mTLS流量
```

证书由 istiod 自动签发和轮换，不用自己管理 CA。服务间通信加密，防止内网嗅探。

## 六、可观测性

Istio 自带可观测性，不用每个服务接 SDK：

- **追踪**：Envoy 自动生成 span，trace_id 自动传播，配合 Jaeger 看调用链
- **指标**：Envoy 自动上报请求量、延迟、错误率，Prometheus 采集，Grafana 有现成 dashboard
- **日志**：Envoy 访问日志，包含源服务、目标服务、状态码、延迟

Kiali 是 Istio 的可视化工具，能看到服务间调用拓扑图：

```bash
kubectl apply -f https://raw.githubusercontent.com/istio/istio/release-1.20/samples/addons/kiali.yaml
istioctl dashboard kiali
```

## 七、踩坑经验

1. **Sidecar 资源开销**：每个 Pod 多一个 Envoy 容器，约占 100MB 内存和 5% CPU。Pod 数量多的时候集群资源消耗不小。对非核心服务可以关闭 Sidecar 注入
2. **首次请求延迟高**：Envoy 启动时要从 istiod 拉配置，首次请求可能有几百毫秒延迟。加了 readiness probe，等 Sidecar 就绪后再接收流量
3. **长连接问题**：WebSocket、gRPC 流等长连接，Envoy 默认超时设置可能断开。在 VirtualService 里调大 `timeout` 和 `idleTimeout`
4. **配置下发延迟**：istiod 把配置下发给所有 Sidecar，大规模集群（几百个服务）有秒级延迟。灰度发布时要等配置同步后再验证
5. **和现有 SDK 冲突**：之前服务里有 sentinel 做熔断，和 Istio 熔断叠加了。逐步把代码里的熔断去掉，统一用 Istio
6. **升级风险**：Istio 版本升级要小心，控制面和数据面版本不兼容会出问题。用 canary 升级方式，先升级控制面，再逐步滚动数据面

## 八、效果

| 能力 | 接入前 | 接入后 |
|------|--------|--------|
| 灰度发布 | 改 Nginx，reload 有风险 | 改 weight，秒级生效 |
| 熔断限流 | 每个服务引入 SDK，代码侵入 | Sidecar 统一配置，无侵入 |
| 服务间加密 | 自己搞证书，麻烦 | 自动 mTLS，证书自动轮换 |
| 调用链追踪 | 每个服务接 SDK | Sidecar 自动生成 span |
| 服务拓扑 | 看不到 | Kiali 可视化拓扑图 |

## 九、总结

Istio Service Mesh 落地核心：

1. **无侵入**：流量治理、熔断限流、加密、可观测性都在 Sidecar 里，业务代码零改动
2. **统一配置**：所有服务的治理策略统一用 Istio CRD 配置，不用每个服务搞一套
3. **灰度灵活**：按比例、按用户特征、按来源 IP 多种灰度方式，秒级生效
4. **安全默认**：mTLS 默认开启，证书自动管理，服务间通信加密
5. **可观测开箱**：追踪、指标、日志 Sidecar 自动生成，不用每个服务接 SDK
6. **渐进式接入**：先给核心服务注入 Sidecar，验证稳定后再推广，不要一上来全量

Service Mesh 不是银弹，它增加了系统复杂度和资源开销。如果你的服务数量不多（十几个以内），或者团队对 K8s 和网络不熟悉，不建议上 Istio。但如果服务数量多、流量治理需求复杂、有合规安全要求，Istio 能大幅降低治理成本。我们是服务到了 30+ 之后才上的，收益明显大于成本。
