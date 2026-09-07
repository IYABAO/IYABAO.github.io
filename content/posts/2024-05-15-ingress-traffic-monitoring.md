---
title: "Ingress 流量监控体系：从零到全景"
date: 2024-05-15T09:00:00+08:00
lastmod: 2024-05-15T09:00:00+08:00
draft: false
author: IYABAO
tags:
  - Kubernetes
  - Ingress
  - 监控
  - Prometheus
categories:
  - 技术
summary: "入口流量是观察系统的第一扇窗。Ingress-Nginx + Prometheus 指标 + 自定义 Grafana 大盘，把请求量、延迟、错误率、上游状态一屏看全，异常 5 分钟内就能定位。"
---

# Ingress 流量监控体系：从零到全景

K8s 里所有外部流量都过 Ingress，它天生是"全站流量的观测点"。搭一套 Ingress 流量监控，等于给全站装了一个仪表盘：**请求量、延迟、错误率、哪个上游在抖，一屏全看。**

## 一、指标来源：Ingress-Nginx 自带

Ingress-Nginx Controller 默认暴露 Prometheus 指标端点（`:10254/metrics`），核心指标：

```
nginx_ingress_controller_requests        # 请求数（带 host/ingress/service 标签）
nginx_ingress_controller_request_duration_seconds   # 请求耗时（直方图）
nginx_ingress_controller_ingress_upstream_latency_seconds  # 上游延迟
nginx_ingress_controller_response_size
```

**这些指标天然带标签**：`ingress`、`namespace`、`service`、`status`——不需要应用埋点，就能按服务/域名维度切流量。

## 二、采集：ServiceMonitor

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: ingress-nginx
spec:
  endpoints:
  - port: metrics
    interval: 15s
  selector:
    matchLabels:
      app.kubernetes.io/name: ingress-nginx
```

配好 Prometheus 自动抓取，无需 agent。**注意开 `enable-ssl-chain-completion` 之外，还要确认 controller 启动参数带 `--metrics-per-host` 和 `--metrics-per-service`**，否则指标是全局聚合的，没法按服务看。

## 三、核心指标设计：四个必看面板

### 1. 请求量（QPS 趋势）

```
sum(rate(nginx_ingress_controller_requests{controller_class="nginx"}[5m])) by (ingress)
```

### 2. 延迟（P50/P95/P99）

直方图算分位：

```promql
histogram_quantile(0.99,
  sum(rate(nginx_ingress_controller_request_duration_seconds_bucket[5m])) by (le, ingress))
```

### 3. 错误率

```
sum(rate(nginx_ingress_controller_requests{status=~"5.."}[5m])) by (ingress)
/
sum(rate(nginx_ingress_controller_requests[5m])) by (ingress)
```

### 4. 上游健康（哪个 Pod 在抖）

```
nginx_ingress_controller_ingress_upstream_latency_seconds
```

**告警规则**（3 条就够）：

| 规则 | 表达式 | 阈值 |
|---|---|---|
| 5xx 率突增 | 错误率 > 5% 持续 5m | warn |
| P99 超时 | 延迟 P99 > 1s 持续 10m | warn |
| 单服务 5xx 持续 | 某 ingress 5xx > 10% 持续 5m | critical |

## 四、Grafana 大盘布局

我按"入口 → 出口"顺序排面板：

```
第一行：总览（总 QPS / 总错误率 / P99 全局）
第二行：按 Ingress（服务）维度表格——QPS、P99、错误率、趋势 sparkline
第三行：Top 慢接口 / Top 5xx 接口
第四行：上游延迟分布
```

**最有价值的是第二行**：一个表格按服务列出 QPS/P99/错误率，任何异常一眼可见。配上 Grafana 变量（`$ingress` 下拉），点进去看单服务详情。

## 五、踩坑记录

### 坑 1：指标没按服务拆分

早期 controller 没开 `--metrics-per-service`，面板上只有全局 QPS，服务一多根本没法看。**改启动参数后重装，才能按 service 维度切。**

### 坑 2：Ingress 没有 namespace 标签歧义

两个 namespace 下同名 ingress，指标标签会打架。用 `namespace + ingress` 组合建变量，别只用 ingress 名。

### 坑 3：直方图 bucket 覆盖不足

默认 bucket 上限 10s，P99 1s 内的服务分位估算不准。**加长尾 bucket**（`2s, 5s, 10s`），分位才可信。

### 坑 4：404 也算请求

`status=404` 也会进 requests 计数，恶意扫描会让"错误率"面板虚高。**看错误率只统计 5xx**，4xx 单独面板（能看出扫描/爬虫）。

## 六、收益

- **上线即用**：不改一行业务代码，全站流量视图就有了
- **排障提速**：告警直接指到"哪个服务 5xx 了"，不用再猜
- **容量规划**：QPS 趋势 + 分位延迟，扩容有数据依据
- **发布监控**：每次发版盯错误率面板，回滚有依据

## 总结

Ingress 流量监控是最划算的可观测投资：

1. **Ingress 自带指标**，配好 ServiceMonitor 就有数据
2. **按服务维度看**：QPS / P99 / 错误率三件套
3. **告警要收敛**：3 条规则比 30 条更有效
4. **面板从入口到出口**：总览 → 服务 → 接口 → 上游

**入口流量是系统的第一道仪表盘，比埋点快、比日志直观，先搭它。**
