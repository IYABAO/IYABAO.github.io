---
title: "Kubernetes 异构队列调度实践：PHP 与 Go 混合部署的资源编排"
date: 2023-09-22T15:00:00+08:00
draft: false
tags: ["Kubernetes", "调度", "PHP", "Go", "混合部署", "资源编排"]
categories: ["云原生"]
summary: "Kubernetes 集群中 PHP 与 Go 服务混合部署的异构队列调度实践，涵盖节点亲和性、污点容忍、资源配额、HPA 自动扩缩容，解决不同语言服务资源需求差异大的问题。"
keywords: ["Kubernetes", "异构队列", "PHP", "Go", "调度"]
---

我们的 K8s 集群里同时跑着 PHP 和 Go 两种语言的服务，资源需求差异很大——PHP 是多进程模型，内存占用高但 CPU 相对低；Go 是协程模型，内存占用低但 CPU 密集。混合部署时如果不做调度优化，会出现资源浪费和互相影响的问题。今天把异构队列调度的实践分享出来。

## 一、问题

1. **资源需求差异**：PHP Pod 需要 1C2G，Go Pod 需要 2C0.5G，混部时资源碎片化
2. **互相影响**：PHP 和 Go 跑在同一节点，Go 的 CPU 密集型任务会影响 PHP 的响应时间
3. **扩缩容不同步**：PHP 和 Go 的流量峰值时间不同，HPA 扩缩容策略不一样
4. **节点资源不均**：有的节点 CPU 满了内存还有剩，有的节点内存满了 CPU 还有剩

## 二、节点分组

用节点标签把节点分成不同资源池：

```bash
# CPU 密集型节点（跑 Go 服务）
kubectl label node node-1 node-type=cpu-intensive
kubectl label node node-2 node-type=cpu-intensive

# 内存密集型节点（跑 PHP 服务）
kubectl label node node-3 node-type=memory-intensive
kubectl label node node-4 node-type=memory-intensive

# 通用节点
kubectl label node node-5 node-type=general
```

## 三、调度策略

### 3.1 节点亲和性

PHP 服务调度到内存密集型节点：

```yaml
affinity:
  nodeAffinity:
    requiredDuringSchedulingIgnoredDuringExecution:
      nodeSelectorTerms:
      - matchExpressions:
        - key: node-type
          operator: In
          values: ["memory-intensive", "general"]
    preferredDuringSchedulingIgnoredDuringExecution:
    - weight: 100
      preference:
        matchExpressions:
        - key: node-type
          operator: In
          values: ["memory-intensive"]
```

Go 服务调度到 CPU 密集型节点，类似配置。

### 3.2 污点与容忍

给专用节点加污点，防止不相关的 Pod 调度上来：

```bash
kubectl taint node node-1 dedicated=cpu:NoSchedule
```

Go 服务加容忍：

```yaml
tolerations:
- key: "dedicated"
  operator: "Equal"
  value: "cpu"
  effect: "NoSchedule"
```

### 3.3 Pod 反亲和性

同一服务的 Pod 分散到不同节点，避免单点故障：

```yaml
affinity:
  podAntiAffinity:
    preferredDuringSchedulingIgnoredDuringExecution:
    - weight: 100
      podAffinityTerm:
        labelSelector:
          matchLabels:
            app: php-api
        topologyKey: kubernetes.io/hostname
```

## 四、资源配额

### 4.1 命名空间资源配额

```yaml
apiVersion: v1
kind: ResourceQuota
metadata:
  name: php-team-quota
  namespace: php
spec:
  hard:
    requests.cpu: "20"
    requests.memory: 40Gi
    limits.cpu: "40"
    limits.memory: 80Gi
    pods: "50"
```

### 4.2 LimitRange

```yaml
apiVersion: v1
kind: LimitRange
metadata:
  name: php-limit-range
  namespace: php
spec:
  limits:
  - default:
      cpu: "1"
      memory: "2Gi"
    defaultRequest:
      cpu: "500m"
      memory: "1Gi"
    max:
      cpu: "2"
      memory: "4Gi"
    type: Container
```

## 五、HPA 自动扩缩容

PHP 和 Go 用不同的扩缩容指标：

```yaml
# PHP：基于内存使用率扩缩容（PHP 内存是瓶颈）
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: php-api-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: php-api
  minReplicas: 3
  maxReplicas: 20
  metrics:
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 70

# Go：基于 CPU 使用率扩缩容（Go CPU 是瓶颈）
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: go-api-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: go-api
  minReplicas: 2
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 60
```

## 六、效果

| 指标 | 优化前 | 优化后 |
|------|--------|--------|
| 资源利用率 | 45% | 75% |
| PHP P99 延迟 | 500ms | 200ms |
| Go P99 延迟 | 150ms | 80ms |
| 节点资源碎片化 | 严重 | 基本消除 |
| 扩缩容响应时间 | 3-5分钟 | 1-2分钟 |

## 七、总结

K8s 异构调度核心：

1. **节点分组**：按资源类型（CPU密集/内存密集）给节点打标签
2. **亲和性调度**：不同语言的服务调度到匹配的节点
3. **污点容忍**：专用节点加污点，防止不相关 Pod 调度
4. **资源配额**：按团队/命名空间设置资源配额，防止抢占
5. **差异化 HPA**：PHP 基于内存扩缩容，Go 基于 CPU 扩缩容
6. **监控调优**：持续监控节点资源利用率，调整调度策略

异构集群调度的核心是"让合适的 Pod 跑到合适的节点上"，减少资源碎片化和互相影响。K8s 提供了丰富的调度策略，要根据实际业务场景组合使用，不是越复杂越好，能解决问题就行。
