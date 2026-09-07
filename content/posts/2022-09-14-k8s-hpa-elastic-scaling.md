---
title: "K8s HPA：从配置到压测验证"
date: 2022-09-14T09:00:00+08:00
lastmod: 2022-09-14T09:00:00+08:00
draft: false
author: IYABAO
tags:
  - Kubernetes
  - HPA
  - 弹性伸缩
categories:
  - 技术
summary: "HPA 配置 10 分钟，调好却要一星期。指标选型、稳定窗口、冷却时间、压测验证——把水平自动伸缩从'能用'调到'真的好用'。"
---

# K8s HPA：从配置到压测验证

HPA（Horizontal Pod Autoscaler）是 K8s 的弹性伸缩：CPU 高了加 Pod，低了减 Pod。配置起来 10 分钟，但"**弹性到底灵不灵**"要踩完坑才知道。这篇文章是完整实战。

## 一、最小配置

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: delivery-service
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: delivery-service
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

**含义**：CPU 平均使用率超 60% 就扩容，低于再缩容，范围 2-10 副本。

## 二、核心机制：怎么算的

### 期望副本数公式

```
期望副本 = ceil(当前副本 × 当前指标 / 目标指标)

例：当前 2 副本，平均 CPU 90%，目标 60%
期望副本 = ceil(2 × 90 / 60) = ceil(3) = 3 个
```

### 两个关键窗口

| 参数 | 默认 | 说明 |
|---|---|---|
| `--horizontal-pod-autoscaler-sync-period` | 15s | 指标采集周期 |
| `--horizontal-pod-autoscaler-cpu-initialization-period` | 5m | Pod 启动 5 分钟内不参与指标计算 |

**坑**：扩容要等**指标周期 + 决策周期**，不会瞬间加 Pod——压测时"打了 30 秒才有反应"是正常的。

## 三、HPA 的坑（实战记录）

### 坑 1：只配 CPU 不够，QPS 高峰 CPU 不高

我们的简历服务是 IO 密集型（大量 ES 调用），CPU 一直 30%，但 QPS 翻倍时延迟暴涨——**CPU 指标根本不触发扩容**。

**解法：自定义指标（QPS 或 P99 延迟）**：

```yaml
metrics:
- type: Pods
  pods:
    metric:
      name: http_requests_per_second
    target:
      type: AverageValue
      averageValue: 200   # 每 Pod 超 200 QPS 扩容
```

需要 Prometheus Adapter 把业务指标暴露给 HPA：

```
Prometheus 采集 http_requests_total
  → prometheus-adapter（custom metrics API）
  → HPA 读取 → 触发伸缩
```

### 坑 2：扩容慢、缩容快是错觉

默认行为：

- **扩容**：只要超过目标，立即扩（每次翻倍 +1）
- **缩容**：`--horizontal-pod-autoscaler-downscale-stabilization-window` 默认 5 分钟——指标低于目标后要等 5 分钟才缩

**这是设计**：防止抖动（流量一会高一会低疯狂增删 Pod）。但高峰期突然腰斩时，5 分钟缩容太慢，浪费钱：

```bash
kube-controller-manager:
  --horizontal-pod-autoscaler-downscale-stabilization-window=3m
```

### 坑 3：Pod 启动慢导致伸缩震荡

服务启动要 40s（加载配置、预热缓存），HPA 看到 CPU 低就缩容，刚缩完流量来了又扩——**震荡**。

**解法**：

1. `readinessProbe` 就绪才接流量（HPA 只统计就绪 Pod）
2. `initialDelaySeconds` 给足启动时间
3. 业务层：扩容预留缓冲（minReplicas 别设 1，至少 2-3）

### 坑 4：单实例指标抖动

Pod 数少时，一个 Pod 的 GC/慢请求会把平均指标拉爆，误扩容。

**解法**：指标聚合窗口拉长（Prometheus 用 5m rate 而不是瞬时值）。

## 四、压测验证：弹性到底灵不灵

配置完必须压测验证，我的标准流程：

```bash
# 1. 用 k6/wrk 打流量，从 100 QPS 线性升到 2000
k6 run --vus 200 --duration 5m load.js

# 2. 同时观察：
kubectl get hpa delivery-service -w      # 看副本数变化
kubectl top pods                         # 看实际资源
```

**验收标准**：

```
✅ 流量升到阈值后，副本数在 2-5 分钟内升到预期
✅ 扩容后 P99 延迟回落（服务恢复）
✅ 流量降后，副本数在稳定窗口后回缩
✅ 全程无 5xx 持续（扩容滞后期允许短暂）
```

## 五、最佳实践清单

```
✅ 多指标：CPU + QPS 双指标（业务指标更贴真实负载）
✅ minReplicas 留缓冲（至少 2，防止缩到底）
✅ 扩容上限考虑下游：DB/ES 连接数上限决定 maxReplicas
✅ 启动探针就绪才接流量
✅ 缩容稳定窗口 3-5 分钟
✅ 定期压测验证（每次发版后重跑）
```

**maxReplicas 别拍脑袋**：扩到 20 个 Pod，数据库连接池扛得住吗？**扩容是系统性的**，不只是 K8s 的事。

## 总结

HPA 的核心认知：

1. **CPU 指标只对计算型服务有效**，IO 型/业务型要配自定义指标
2. **伸缩不是即时的**，指标周期 + 稳定窗口，别期望秒级响应
3. **震荡是头号敌人**：探针就绪 + 缓冲副本 + 稳定窗口
4. **压测验证**：不压测的 HPA 配置等于没配

**弹性伸缩的终点不是"能扩"，是"扩得及时、缩得稳定、下游扛得住"。**
