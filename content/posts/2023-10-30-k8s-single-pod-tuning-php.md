---
title: "K8s 单 Pod 性能调优：PHP-FPM 与 Opcache 的极限"
date: 2023-10-30T09:00:00+08:00
lastmod: 2023-10-30T09:00:00+08:00
draft: false
author: IYABAO
tags:
  - Kubernetes
  - PHP
  - PHP-FPM
  - Opcache
  - 性能调优
categories:
  - 技术
summary: "微服务都拆 Go 了，但存量 PHP 服务还得在 K8s 里活着。一个 Pod 里 PHP-FPM 并发调多少、Opcache 怎么预热、CPU 请求怎么配，这些细节决定了一个 Pod 能吃多少流量。"
---

# K8s 单 Pod 性能调优：PHP-FPM 与 Opcache 的极限

公司存量 PHP 服务迁到 K8s 后，第一波"降本增效"就是**压单 Pod 的吞吐**。一个 1C2G 的 Pod 到底能扛多少 QPS？我从 PHP-FPM 并发模型、Opcache 预热、资源配置三个角度，把单 Pod 性能调到了极限。

## 一、PHP-FPM：并发不是越高越好

PHP-FPM 是进程模型，一个 `pm.max_children` 就是同时能处理的请求数。K8s 里最常见的问题：**配了 50 个 worker，每个 worker 吃 30MB，2G 内存直接 OOM。**

### 正确姿势：按内存算上限

```
可用内存 1.5G（留 25% 给 OPCache/系统）
单个 worker 峰值内存 40MB（压测实测）
max_children = 1.5G / 40M ≈ 37 → 保守取 30
```

```ini
pm = dynamic
pm.max_children = 30
pm.start_servers = 8
pm.min_spare_servers = 4
pm.max_spare_servers = 12
pm.max_requests = 500
```

**`pm.max_requests = 500` 必须设**：防止 PHP 进程长期运行内存泄漏累积。K8s 里 Pod 会滚动重启，但进程内泄漏 500 请求内也该释放一次。

### 真正决定并发的是"请求耗时 × QPS"

worker 数和 QPS 的关系：

```
并发数 = 平均响应时间(秒) × QPS
例：响应 200ms，目标 150 QPS → 并发 = 0.2 × 150 = 30 worker
```

**别拍脑袋配 50**，先压测拿到响应时间，再算并发。这是最常被忽略的计算。

## 二、Opcache：K8s 里最容易踩的坑

### 坑：Pod 重启后 Opcache 冷启动

本地/虚拟机里 PHP-FPM 常驻，Opcache 编译缓存是热的。K8s 里 Pod 随时重建，**每次重建都是冷缓存**——第一个请求要把全部 PHP 文件重新编译一次，QPS 瞬间打回原形，持续 30~60 秒。

### 解法 1：初始化容器预热

```yaml
initContainers:
- name: opcache-warmup
  image: your-php-image
  command: ["php", "/var/www/bin/opcache_warmup.php"]
```

服务启动前先跑一遍预热脚本，把所有入口文件的 Opcache 编译一遍。**注意：initContainer 和主容器共享同一个卷，但 Opcache 是进程内缓存，跨容器不共享**——所以预热要在**同一个容器启动命令里做**，而不是 initContainer（进程不同）。

正确做法：主容器 entrypoint 改为 `预热 && 启动 FPM`：

```bash
#!/bin/bash
# docker-entrypoint.sh
php opcache_warmup.php   # 预编译全部 PHP 文件
php-fpm -F
```

### 解法 2：就绪探针给足热身时间

```yaml
readinessProbe:
  httpGet: { path: /healthz, port: 9000 }
  initialDelaySeconds: 10   # 给预热留时间
  periodSeconds: 5
  failureThreshold: 6
```

### Opcache 关键配置

```ini
opcache.enable = 1
opcache.memory_consumption = 128        # 够装全量字节码
opcache.interned_strings_buffer = 16
opcache.max_accelerated_files = 20000   # 覆盖全部 PHP 文件数
opcache.validate_timestamps = 0         # 生产关掉文件 mtime 检查
opcache.revalidate_freq = 0
```

**`validate_timestamps = 0` 很重要**：K8s 里代码通过镜像发布，不是热改文件，关掉 mtime 检查能省掉每次请求的 stat 开销。

## 三、资源配置：K8s 的 CPU 配额会卡 PHP-FPM

### CPU Request 不是"够用就行"

PHP-FPM 是**计算密集型**（每次请求都要执行字节码），CPU 配额直接影响吞吐。K8s 的 `cpu: 1000m` 意味着最多用 1 核，`requests: 500m` 会影响 CFS 调度配额。

**经验值**：PHP 服务 CPU request 给足（`500m~1000m`），limit 比 request 高 50%（`1500m`），让 CPU 突发有空间。**PHP 服务 CPU 没给够，加再多 worker 也是排队。**

### 内存：Opcache 也是内存大户

```
PHP-FPM 30 worker × 40MB = 1.2G
Opcache 128MB + interned strings 16MB
系统 + 缓冲 ≈ 200MB
→ 请求 1.8G，limit 2G，留 10% 余量
```

## 四、压测结果

| 配置 | 单 Pod（1C2G）QPS |
|---|---|
| 初始配置（50 worker + 无预热 + 冷启动） | 40，重启后 5 秒内跌到 5 |
| 调优后（30 worker + 预热 + validate_timestamps=0） | 220（稳定） |
| 调优后 + CPU request 1C | 320 |

## 总结

K8s 里跑 PHP 的要点：

1. **worker 数按内存算，按响应时间×QPS 验算**，不是拍脑袋
2. **Opcache 冷启动是 K8s 特有的坑**：entrypoint 预热 + 关闭 mtime 校验
3. **CPU 配额影响计算型负载**：request 给足，limit 留突发
4. Pod 重启是常态，一切性能措施都要**扛得住冷启动**

PHP 在 K8s 里不是不能跑，是**不能按虚拟机的习惯跑**。想清楚这三件事，单 Pod 吞吐能翻好几倍。
