---
title: "eBPF 在 K8s 中的应用：无侵入式可观测性与性能分析"
date: 2025-10-12T14:00:00+08:00
draft: false
tags: ["eBPF", "K8s", "可观测性", "性能分析", "云原生", "网络"]
categories: ["云原生"]
summary: "eBPF 技术在 Kubernetes 中的实战应用，涵盖无侵入式可观测性、网络监控、性能分析、安全审计，以及 Cilium、Pixie、Parca 等工具的选型和落地经验。"
---

eBPF（extended Berkeley Packet Filter）是近年来云原生领域最火的技术之一，被称为"Linux 内核的 JavaScript"——能在内核里安全地运行自定义程序，不需要修改内核代码、不需要加载内核模块。2025年我们在 K8s 集群里落地了 eBPF 可观测性方案，今天把实践经验分享出来。

## 一、什么是 eBPF

eBPF 是 Linux 内核的一个特性，允许用户在不修改内核源码、不加载内核模块的情况下，在内核里运行自定义程序。程序通过验证器（Verifier）确保安全（不会崩溃内核、不会无限循环），然后挂载到内核的各种事件点（系统调用、网络事件、函数调用等），事件触发时执行。

**核心特点**：
1. **无侵入**：不需要修改应用代码，不需要重启应用，不需要 sidecar
2. **高性能**：在内核态运行，比用户态代理性能高很多
3. **安全**：验证器确保程序安全，不会影响内核稳定性
4. **可编程**：可以自定义程序逻辑，实现各种功能

**eBPF 能做什么**：
- 网络：网络策略、负载均衡、流量监控、服务网格
- 可观测性：分布式追踪、指标采集、日志、性能分析
- 安全：运行时安全、系统调用审计、入侵检测
- 性能：性能分析、火焰图、锁竞争分析

## 二、为什么用 eBPF

传统的 K8s 可观测性方案有几个痛点：

1. **Sidecar 资源开销大**：Istio 等服务网格用 Envoy sidecar，每个 Pod 多一个容器，内存占用 100-200MB，集群里几千个 Pod 就是几十 GB 额外内存
2. **应用侵入**：分布式追踪需要在应用代码里埋点，每个服务都要改，语言栈多了维护成本高
3. **指标不全**：传统的 node_exporter 只能拿到节点级指标，Pod 级、容器级、进程级的网络和性能指标拿不到
4. **性能分析难**：应用性能问题排查，需要重新编译应用加 profiling，生产环境不敢随便搞

eBPF 解决了这些问题：
- **无侵入**：不需要 sidecar，不需要改应用代码
- **内核级**：能拿到内核态的详细数据，网络、系统调用、文件 IO 都能监控
- **高性能**：在内核态聚合数据，比用户态采集开销小
- **全覆盖**：Pod、容器、进程、节点各级别的数据都能拿到

## 三、eBPF 工具生态

eBPF 生态已经很成熟了，几个主流工具：

| 工具 | 领域 | 说明 |
|------|------|------|
| Cilium | 网络 + 安全 | eBPF 网络和安全方案，替代 kube-proxy，支持网络策略、可观测性 |
| Pixie | 可观测性 | 无侵入式可观测性，自动采集分布式追踪、指标、日志 |
| Parca | 性能分析 | 持续性能分析，eBPF 采集 CPU profile，生成火焰图 |
| Tetragon | 安全 | eBPF 运行时安全，系统调用审计、入侵检测 |
| bcc / bpftrace | 底层工具 | eBPF 编程工具，写自定义 eBPF 程序 |
| Hubble | 网络可观测 | Cilium 的网络可观测性组件，服务依赖图、流量监控 |

我们主要用了 Cilium（网络+可观测性）和 Parca（性能分析），Pixie 做了评估但没上生产。

## 四、Cilium 落地

Cilium 是最成熟的 eBPF 方案，用 eBPF 实现了 K8s 的网络和安全，替代 kube-proxy。

### 为什么换 Cilium

之前用的是 kube-proxy（iptables 模式），问题：
- 服务多了之后 iptables 规则爆炸，Service 数量上千时 kube-proxy 同步规则很慢
- 网络策略（NetworkPolicy）功能弱，只能按 IP/端口，不能按 L7（HTTP 方法、路径）
- 网络可观测性差，看不到服务间调用关系、流量拓扑
- 负载均衡是 iptables NAT，性能一般

Cilium 用 eBPF 在内核里做负载均衡和网络策略，性能更好、功能更强。

### 安装

```bash
# 用 Helm 安装 Cilium
helm repo add cilium https://helm.cilium.io/
helm install cilium cilium/cilium \
  --namespace kube-system \
  --set kubeProxyReplacement=strict \       # 完全替代 kube-proxy
  --set hubble.relay.enabled=true \         # 启用 Hubble Relay
  --set hubble.ui.enabled=true \             # 启用 Hubble UI
  --set prometheus.enabled=true \            # 启用 Prometheus 指标
  --set operator.prometheus.enabled=true \
  --set l2announcements.enabled=true \       # L2 公告（替代 MetalLB）
  --version 1.15.0
```

### 网络策略

Cilium 支持 L3/L4/L7 网络策略：

```yaml
# L7 网络策略：只允许 GET /api/resume/*
apiVersion: cilium.io/v2
kind: CiliumNetworkPolicy
metadata:
  name: resume-api-policy
spec:
  endpointSelector:
    matchLabels:
      app: resume-service
  ingress:
  - fromEndpoints:
    - matchLabels:
        app: api-gateway
    toPorts:
    - ports:
      - port: "8080"
        protocol: TCP
      rules:
        http:
        - method: "GET"
          path: "/api/resume/.*"
        - method: "POST"
          path: "/api/resume"
```

这个策略只允许 api-gateway 访问 resume-service 的 8080 端口，且只允许 GET /api/resume/* 和 POST /api/resume，其他请求全部拒绝。传统 NetworkPolicy 做不到 L7 控制。

### Hubble 网络可观测性

Hubble 是 Cilium 的可观测性组件，能看到：
- 服务依赖拓扑图（哪个服务调用了哪个服务）
- 流量监控（请求量、延迟、错误率）
- 网络策略命中情况（哪些流量被策略拒绝了）
- DNS 查询记录

```bash
# 安装 Hubble CLI
brew install hubble

# 端口转发访问 Hubble UI
kubectl port-forward -n kube-system svc/hubble-ui 8081:80
```

打开 http://localhost:8081 就能看到服务依赖图，直观地看到整个集群的服务调用关系。排查"哪个服务在调用我""为什么流量不通"这类问题超方便。

### 性能对比

替换 kube-proxy 后，网络性能提升明显：

| 指标 | kube-proxy (iptables) | Cilium (eBPF) | 提升 |
|------|----------------------|---------------|------|
| Service 数量 100 时的 kube-proxy 同步时间 | 2s | <100ms | 95% |
| Service 数量 1000 时的同步时间 | 30s | <1s | 97% |
| Pod 间通信延迟 P99 | 1.2ms | 0.8ms | 33% |
| 网络策略规则匹配性能 | O(n) 线性 | O(1) 哈希 | 大幅提升 |

Service 数量多的时候，Cilium 的优势特别明显。

## 五、Parca 持续性能分析

Parca 是基于 eBPF 的持续性能分析工具，能在生产环境持续采集 CPU profile，不需要修改应用代码，不需要重启。

### 为什么需要持续性能分析

传统的性能分析（pprof、火焰图）是"按需"的——出问题了才去抓 profile，可能问题已经复现不了了。持续性能分析是"一直开着"，随时可以回看任意时间段的性能数据，像性能领域的"监控摄像头"。

### 安装

```bash
# 用 Helm 安装 Parca
helm repo add parca https://charts.parca.dev
helm install parca parca/parca-agent \
  --namespace parca \
  --create-namespace \
  --set parcaAddress=parca.parca.svc:7070
```

Parca Agent 以 DaemonSet 方式运行在每个节点上，用 eBPF 采集所有进程的 CPU profile，发送给 Parca Server 存储和分析。

### 使用

Parca UI 里可以：
- 选择时间段、服务、节点，查看 CPU 火焰图
- 对比两个时间段的 profile，看性能变化
- 查看 Top N 最耗 CPU 的函数
- 按 Pod、容器、进程筛选

排查"这个服务为什么 CPU 高"这类问题，不用再手动抓 pprof 了，直接在 Parca UI 里看火焰图，一眼就能看到哪个函数在耗 CPU。

### 效果

之前排查一次线上性能问题，从发现问题到定位根因平均要 30 分钟（要复现、抓 profile、分析）。用了 Parca 后，直接回看问题时间段的火焰图，5 分钟就能定位。

## 六、Pixie 评估

Pixie 是另一个 eBPF 可观测性工具，特点是"零配置"——安装后自动采集分布式追踪、指标、日志，不需要应用埋点。

我们做了评估，优点：
- 真·零配置，装完就能用，自动发现服务和调用链
- 分布式追踪不需要应用埋点，eBPF 自动采集 HTTP/gRPC 请求
- 内置脚本语言（PxL），可以自定义查询和仪表盘
- UI 漂亮，交互好

缺点：
- 资源开销大，Pixie 本身比较重，每个节点要占 1-2 核 CPU
- 数据存在 Pixie 云（虽然可以自托管，但配置复杂）
- 企业版收费，免费版有功能限制
- 团队对 eBPF 底层不够熟悉，出问题排查困难

最终没上生产，主要原因是资源开销大，而且我们已经有了 Cilium + Prometheus + Jaeger 的可观测性体系，Pixie 的功能重叠较多。如果是小团队、不想自己搭可观测性体系，Pixie 是很好的选择。

## 七、自定义 eBPF 程序

成熟工具覆盖不了的场景，可以自己写 eBPF 程序。用 bpftrace 快速写：

```bash
# 统计每个进程的 TCP 连接数
bpftrace -e '
kprobe:tcp_v4_connect {
    @[comm] = count();
}
interval:10s {
    print(@);
    clear(@);
}
'

# 监控哪个进程在写大文件
bpftrace -e '
tracepoint:syscalls:sys_enter_write {
    @bytes[comm] = sum(args->count);
}
interval:5s {
    printf("%-20s %s\n", "PROCESS", "BYTES_WRITTEN");
    print(@, 10);
    clear(@);
}
'
```

复杂的用 bcc 或 libbpf 写 C 程序，编译成 eBPF 字节码加载。我们写了一个自定义 eBPF 程序，监控 MySQL 慢查询（在系统调用层捕获 SQL 语句和执行时间），不需要改 MySQL 配置，也不需要开慢查询日志。

## 八、踩坑经验

1. **内核版本要求**：eBPF 需要较新的内核（4.19+，推荐 5.4+），老内核很多功能用不了。升级内核是第一步，我们的集群内核是 5.15，大部分功能都支持
2. **Cilium 替换 kube-proxy 要小心**：不能直接删 kube-proxy，要先让 Cilium 和 kube-proxy 共存（kubeProxyReplacement=partial），验证没问题再切到 strict 模式完全替代
3. **eBPF 程序有验证器限制**：程序不能无限循环、不能有未初始化变量、复杂度有限制。写复杂程序时可能被验证器拒绝，需要简化逻辑
4. **资源开销不能忽视**：虽然 eBPF 比 sidecar 轻，但也不是零开销。Cilium + Parca 在每个节点大约占 0.5-1 核 CPU，几百 MB 内存。要监控 eBPF 工具本身的资源使用
5. **调试困难**：eBPF 程序在内核里跑，调试比用户态程序难很多。bpf_trace_printk 打印调试信息，用 bpftool 查看程序状态，需要一定的内核知识
6. **安全风险**：eBPF 程序能访问内核数据，虽然有验证器，但复杂程序仍可能有安全风险。只运行可信的 eBPF 程序，限制 eBPF 系统调用权限
7. **和现有工具的兼容**：Cilium 替换 kube-proxy 后，有些依赖 iptables 的工具（如某些网络插件、安全工具）可能不兼容。迁移前要评估所有依赖网络的组件
8. **学习曲线陡**：eBPF 涉及内核、网络、编程，学习成本高。建议先用成熟工具（Cilium、Parca），不需要自己写 eBPF 程序，等熟悉了再考虑自定义

## 九、总结

eBPF 在 K8s 中的应用核心：

1. **无侵入是最大优势**：不需要 sidecar、不需要改应用代码、不需要重启，内核级采集，这是 eBPF 相比传统方案的核心优势
2. **Cilium 是首选网络方案**：替代 kube-proxy，性能更好、功能更强（L7 网络策略）、可观测性更好，Service 多的集群收益明显
3. **Parca 持续性能分析**：生产环境一直开着 CPU profile，随时回看，排查性能问题从 30 分钟降到 5 分钟
4. **Pixie 适合小团队**：零配置、开箱即用，但资源开销大，大团队建议自己搭可观测性体系
5. **自定义 eBPF 是高级玩法**：成熟工具覆盖不了的场景再自己写，bpftrace 快速验证，bcc/libbpf 写生产级程序
6. **内核版本是基础**：先升级内核到 5.4+，否则很多 eBPF 功能用不了
7. **资源开销要监控**：eBPF 不是零开销，要监控工具本身的资源使用，避免影响业务
8. **学习曲线陡但值得**：eBPF 是云原生的未来技术，投入时间学习，长期收益大

eBPF 被称为"云原生的下一个十年"，它正在改变 K8s 的网络、可观测性、安全、性能分析的实现方式。从 sidecar 到 eBPF，从应用侵入到内核无侵入，这是技术演进的方向。建议技术团队尽早关注和尝试 eBPF，先用成熟工具（Cilium）落地，再逐步深入。它不会让你立刻解决所有问题，但会让你的可观测性和网络能力提升一个量级。
