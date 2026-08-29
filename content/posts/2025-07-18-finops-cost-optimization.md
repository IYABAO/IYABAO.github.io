---
title: "云原生成本优化 FinOps：K8s 资源利用率提升与成本治理"
date: 2025-07-18T14:00:00+08:00
draft: false
tags: ["FinOps", "成本优化", "K8s", "云原生", "资源治理", "可观测性"]
categories: ["云原生"]
summary: "云原生环境下的 FinOps 成本治理实践，涵盖 K8s 资源利用率分析、请求限制优化、自动扩缩容、Spot 实例、存储优化、成本分摊，以及从每月云账单下降 40% 的实战经验。"
---

微服务上 K8s 之后，服务器数量越来越多，云账单月月涨，但很多资源其实闲着。2025年我们做了一次全面的 FinOps（云财务运营）治理，通过资源优化、弹性伸缩、Spot 实例等手段，每月云成本下降了 40%。今天把实战经验分享出来。

## 一、为什么需要 FinOps

上云初期大家都"先跑起来再说"，资源申请随便填，CPU 申请 8 核实际用 1 核，内存申请 16G 实际用 2G，这种情况很常见。结果就是：

- **资源利用率低**：集群平均 CPU 利用率 15%，内存利用率 25%，大部分资源闲着
- **成本不可控**：云账单月月涨，不知道哪个服务、哪个团队花了多少钱
- **资源申请随意**：开发申请资源按"感觉"来，多多益善，没人审核
- **没有成本意识**：技术团队只关心性能和稳定性，不关心花了多少钱

FinOps 的核心就是**把云成本纳入技术决策**，让技术团队有成本意识，在性能、稳定性、成本之间做平衡。

## 二、FinOps 三阶段

FinOps 基金会定义了三个阶段：

1. **Inform（可见）**：能看到钱花在哪了，按团队/服务/环境分摊成本
2. **Optimize（优化）**：识别浪费，优化资源，降低成本
3. **Operate（运营）**：建立成本治理流程，持续优化，成本纳入 KPI

我们也是按这个顺序推进的。

## 三、第一阶段：成本可见

优化之前先得知道钱花在哪了。

### 成本标签

所有云资源打标签，按团队、服务、环境分类：

```yaml
# K8s 资源标签
labels:
  team: backend          # 团队
  service: resume-service  # 服务
  env: production        # 环境
  cost-center: hr-platform  # 成本中心
```

云服务器、数据库、对象存储、负载均衡都要打标签，没标签的资源归到"未分配"，倒逼团队补标签。

### 成本分摊工具

用开源工具做成本可视化：
- **OpenCost**：K8s 成本分摊，按 namespace/label 统计
- **Kubecost**：OpenCost 的商业版，功能更全
- **云厂商账单**：阿里云/腾讯云/AWS 的成本分析，按标签分摊

部署 OpenCost 后，能看到每个服务、每个团队的实时成本：

```text
服务成本排行（本月）：
1. resume-service   ¥12,500  CPU 8核 内存16G × 3实例
2. job-service      ¥9,800   CPU 8核 内存16G × 2实例
3. ai-gateway       ¥8,200   CPU 16核 内存32G × 1实例（GPU）
4. user-service     ¥5,600   CPU 4核 内存8G × 3实例
...
未分配资源          ¥15,000  （没打标签的资源，重点治理对象）
```

### 成本大盘

做 Grafana dashboard，展示：
- 总成本趋势（按月/周/日）
- 按团队成本占比
- 按服务成本排行
- 资源利用率（CPU/内存）
- 预估月度账单

让每个团队都能看到自己花了多少钱，利用率怎么样。

## 四、第二阶段：成本优化

这是核心，我们做了以下优化。

### 1. 资源请求（Requests/Limits）优化

这是最大的浪费来源。K8s 里 Pod 的 resources.requests 是预留资源，不管实际用不用，节点都要预留这么多。

**问题**：
```yaml
# 典型的过度申请
resources:
  requests:
    cpu: "4"       # 申请4核，实际平均用0.5核
    memory: "8Gi"  # 申请8G，实际平均用1.5G
  limits:
    cpu: "8"
    memory: "16Gi"
```

**优化方法**：

用 Prometheus + Grafana 看每个服务的实际资源使用：

```promql
# CPU 使用率 P95
histogram_quantile(0.95, sum(rate(container_cpu_usage_seconds_total{container!=""}[5m])) by (le, pod))

# 内存使用率 P95
quantile_over_time(0.95, container_memory_working_set_bytes{container!=""}[7d])
```

根据 P95 使用率调整 requests：

```yaml
# 优化后
resources:
  requests:
    cpu: "1"        # 从4核降到1核（P95实际0.8核）
    memory: "2Gi"   # 从8G降到2G（P95实际1.8G）
  limits:
    cpu: "2"        # limits 是 requests 的2倍，允许突发
    memory: "4Gi"
```

**经验值**：
- CPU requests = P95 实际使用 × 1.2（留 20% 余量）
- 内存 requests = P95 实际使用 × 1.3（内存不能超，余量多留一点）
- CPU limits = requests × 2（允许突发流量）
- 内存 limits = requests × 1.5（内存 OOM 会杀 Pod，不要太极限）

**效果**：仅这一项，集群资源需求减少了 50%，同样的节点能跑两倍的 Pod。

### 2. 自动扩缩容（HPA/VPA）

流量有波峰波谷，固定副本数会浪费。用 HPA（水平自动扩缩容）根据 CPU/内存/自定义指标自动调整副本数：

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: resume-service
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: resume-service
  minReplicas: 2          # 最少2个（保证高可用）
  maxReplicas: 10         # 最多10个
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 60  # CPU 超过60%就扩容
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 70  # 内存超过70%就扩容
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 60   # 扩容前观察60秒
      policies:
      - type: Percent
        value: 50
        periodSeconds: 60
    scaleDown:
      stabilizationWindowSeconds: 300  # 缩容前观察5分钟（防止抖动）
      policies:
      - type: Percent
        value: 25
        periodSeconds: 60
```

**VPA（垂直自动扩缩容）**：自动调整 Pod 的 requests/limits，适合无法水平扩容的有状态服务。但 VPA 会重启 Pod，生产环境慎用，建议用 VPA 做"推荐"（只给建议不自动改），人工确认后调整。

**定时扩缩容**：流量有明显时间规律的（如白天高晚上低），用 KEDA 做定时扩缩容：

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: resume-service
spec:
  scaleTargetRef:
    name: resume-service
  minReplicaCount: 2
  maxReplicaCount: 10
  triggers:
  - type: cron
    metadata:
      timezone: Asia/Shanghai
      start: "0 9 * * 1-5"   # 工作日9点开始扩容
      end: "0 21 * * 1-5"    # 工作日21点开始缩容
      desiredReplicas: "8"
```

工作日白天 8 个副本，晚上和周末 2 个副本，成本直接降 60%。

### 3. Spot 实例（抢占式实例）

无状态服务可以跑在 Spot 实例上，价格是按需实例的 30%-50%。Spot 实例可能被云厂商随时回收（提前2分钟通知），所以只适合无状态、可中断的服务。

**适合跑 Spot 的**：
- Web/API 服务（无状态，多副本）
- 异步任务消费者（可重试）
- CI/CD 构建任务
- 测试/预发布环境

**不适合跑 Spot 的**：
- 数据库（有状态，不能随便中断）
- 核心交易服务（中断影响大）
- 长任务（不可中断）

**实现**：用 K8s 的 nodeSelector 或亲和性把无状态服务调度到 Spot 节点池：

```yaml
affinity:
  nodeAffinity:
    preferredDuringSchedulingIgnoredDuringExecution:
    - weight: 100
      preference:
        matchExpressions:
        - key: node-type
          operator: In
          values: ["spot"]
  podAntiAffinity:
    preferredDuringSchedulingIgnoredDuringExecution:
    - weight: 100
      podAffinityTerm:
        labelSelector:
          matchLabels:
            app: resume-service
        topologyKey: kubernetes.io/hostname
```

配合多副本 + Pod 反亲和，即使 Spot 实例被回收，其他节点上的副本还能提供服务，不影响可用性。

### 4. 存储优化

存储也是成本大头，特别是日志和监控数据。

**日志**：
- 热数据（最近7天）存在 SSD，方便查询
- 温数据（7-30天）存在高效云盘
- 冷数据（30天以上）归档到对象存储（OSS/S3），成本是云盘的 1/10
- 用 ELK 的 ILM（索引生命周期管理）自动滚动和归档

**监控**：
- Prometheus 本地只存最近 15 天数据
- 历史数据存到对象存储（用 Thanos 或 VictoriaMetrics）
- 降低采样率，历史数据降采样（5秒采样→1分钟采样→5分钟采样）

**数据库**：
- 冷数据分表归档，历史数据迁到归档库
- 用只读实例分担查询压力，不用盲目升配主库
- 定期清理无用数据（过期日志、临时表、备份）

### 5. 网络优化

- **跨可用区流量收费**：很多云厂商跨 AZ 流量收费，尽量把有频繁通信的服务部署在同一个 AZ，或者用拓扑感知路由
- **NAT 网关流量费**：Pod 访问公网走 NAT 网关，流量费不便宜。能走内网的走内网（对象存储、数据库都有内网端点），不需要公网的 Pod 关闭公网访问
- **负载均衡优化**：不要每个服务一个 LB，用 Ingress 共享一个 LB，或者用 Gateway API

## 五、第三阶段：持续运营

优化不是一次性的，要建立持续运营机制。

### 成本预算和告警

- 每个团队/服务设月度成本预算
- 超预算 80% 告警，超 100% 升级
- 成本异常突增自动告警（可能是资源泄漏或异常流量）

### 资源审核流程

- 新服务申请资源要审核，不能随便申请
- 超过一定规格（如 CPU > 16核）需要架构师审批
- 定期（每季度）复盘资源使用，回收闲置资源

### 成本纳入 KPI

- 把资源利用率、成本下降纳入团队 KPI
- 设立"成本优化奖"，鼓励团队主动优化
- 技术方案评审时必须考虑成本，不能只谈性能

### 闲置资源清理

- 每周扫描未使用的资源：未挂载的云盘、未绑定的公网 IP、空闲的负载均衡、长期没人访问的测试环境
- 测试环境定时关机（下班后和周末自动关机，省 2/3 成本）
- 开发环境用小规格实例，开发够用就行

## 六、我们的优化成果

| 优化项 | 成本下降 | 说明 |
|--------|---------|------|
| Requests/Limits 优化 | 30% | 最大的优化项，资源利用率从15%提升到45% |
| HPA + 定时扩缩容 | 15% | 非高峰时段缩容，测试环境定时关机 |
| Spot 实例 | 20% | 无状态服务跑 Spot，省一半费用 |
| 存储优化 | 10% | 日志归档、监控降采样、数据库冷数据迁移 |
| 闲置资源清理 | 5% | 清理未使用资源、测试环境缩容 |
| **合计** | **约40%** | 每月云账单从 ¥18万 降到 ¥11万 |

资源利用率：CPU 从 15% 提升到 45%，内存从 25% 提升到 55%。

## 七、踩坑经验

1. **requests 调太低导致 OOM**：优化时内存 requests 调得太极限，流量高峰时 Pod OOM 被杀。内存要多留余量（P95 × 1.3），宁可多一点也不要 OOM
2. **HPA 抖动**：CPU 阈值设太低，频繁扩容缩容，Pod 不断重建。调大 stabilizationWindow，扩容快缩容慢，防止抖动
3. **Spot 实例回收影响服务**：初期把核心服务也跑在 Spot 上，实例被回收时服务短暂不可用。只把无状态、多副本的服务跑 Spot，核心服务跑按需实例
4. **降采样丢失关键指标**：监控历史数据降采样太激进，后来排查问题时找不到细粒度数据。热数据保留足够长时间，降采样不要太激进
5. **成本标签遗漏**：很多资源没打标签，成本分摊不准。用自动化工具扫描未标签资源，告警通知负责人补标签，新资源创建时强制要求标签
6. **优化影响性能**：过度优化导致性能下降，用户投诉。优化前后做压测对比，确保性能在可接受范围内，不能为了省成本牺牲用户体验
7. **团队抵触**：开发觉得成本优化是"给自己加活"，不配合。先做成本可视化让大家看到浪费，再用数据说话，最后把优化纳入 KPI，逐步推进

## 八、总结

FinOps 成本治理核心：

1. **先可见再优化**：不知道钱花在哪就没法优化，成本标签和可视化是第一步
2. **资源请求是最大浪费**：requests 过度申请是最常见的浪费，根据实际使用率调整，能省 30%-50%
3. **弹性伸缩是基础**：HPA + 定时扩缩容，按实际流量调整副本数，不要固定高配
4. **Spot 实例降本明显**：无状态服务跑 Spot，省一半费用，但要保证多副本和可中断
5. **存储和网络不要忽视**：日志归档、监控降采样、内网访问，这些加起来也能省 10%-15%
6. **持续运营是关键**：优化不是一次性的，建立预算、告警、审核、KPI 机制，持续治理
7. **性能和成本平衡**：不能为了省成本牺牲性能和稳定性，优化前后要做压测验证

FinOps 的本质是"技术决策要有成本意识"。以前技术团队只关心"能不能跑、快不快、稳不稳"，现在还要加一个"贵不贵"。不是说要一味省钱，而是要在性能、稳定性、成本之间找到最优平衡点。同样花 10 万块，能支撑 10 万 QPS 还是 5 万 QPS，这就是技术能力的体现。
