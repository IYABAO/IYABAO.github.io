---
title: "PHP-FPM 单 Pod 性能调优：从 Opcache 到进程管理的深度优化"
date: 2023-07-05T10:00:00+08:00
draft: false
tags: ["PHP-FPM", "性能调优", "Kubernetes", "Opcache", "Docker"]
categories: ["性能优化"]
summary: "Kubernetes 环境下 PHP-FPM 单 Pod 性能调优实践，从 Opcache 配置、进程管理、资源限制到镜像优化，单 Pod QPS 从 200 提升到 800。"
---

PHP 应用迁移到 Kubernetes 后，PHP-FPM 单 Pod 的性能调优和传统服务器不一样——容器资源受限、进程数要和容器资源匹配、Opcache 在容器里的行为也有差异。今天把 K8s 环境下 PHP-FPM 单 Pod 的调优经验分享出来。

## 一、问题现象

迁移到 K8s 后，PHP-FPM Pod 经常 502，监控显示 PHP-FPM 进程数打满，CPU 使用率不高但请求排队。单 Pod QPS 只能到 200 左右，同样的代码在物理机上能到 500。

## 二、进程数配置

### 问题

PHP-FPM 默认 `pm = dynamic`，`pm.max_children = 5`，进程数太少，并发请求排队。但盲目调大又会导致内存不足 OOM。

### 解决方案

先算单个 PHP-FPM 进程的内存占用，再根据 Pod 内存限制算 max_children：

```bash
# 查看单个 PHP-FPM 进程内存
ps -ylC php-fpm --sort:rss | awk '{sum+=$8; n++} END {print sum/n/1024 " MB"}'
```

假设单进程 60MB，Pod 内存限制 1GB（系统和其他进程留 200MB）：

```
max_children = (1024 - 200) / 60 ≈ 13
```

PHP-FPM 配置：

```ini
[www]
pm = static
pm.max_children = 12
pm.start_servers = 12
pm.min_spare_servers = 6
pm.max_spare_servers = 12
pm.max_requests = 1000
```

- `pm = static`：固定进程数，避免动态创建销毁的开销
- `pm.max_requests = 1000`：每个进程处理 1000 个请求后重启，防止内存泄漏

## 三、Opcache 优化

### 问题

容器里 Opcache 命中率只有 60%，比物理机低很多。原因是容器每次重启 Opcache 都清空，而且 `validate_timestamps` 频繁检查文件更新。

### 解决方案

```ini
[opcache]
opcache.enable=1
opcache.enable_cli=0
opcache.memory_consumption=192
opcache.interned_strings_buffer=16
opcache.max_accelerated_files=20000
opcache.max_wasted_percentage=10
opcache.validate_timestamps=0   ; 生产环境关闭时间戳检查
opcache.revalidate_freq=0
opcache.save_comments=1
opcache.fast_shutdown=1
opcache.preload=/var/www/html/preload.php  ; PHP 7.4+ 预加载
```

关键点：
- `validate_timestamps=0`：生产环境代码不经常变，关闭时间戳检查，命中率提升到 95%+
- 代码更新通过重新构建镜像发布，不需要 Opcache 自动刷新
- `preload` 预加载框架核心类，性能再提升 20%

## 四、镜像优化

### 问题

PHP 镜像 800MB+，启动慢，拉取慢。

### 解决方案

多阶段构建 + 精简基础镜像：

```dockerfile
# 构建阶段
FROM php:7.4-fpm-alpine AS builder
RUN apk add --no-cache autoconf g++ make
RUN docker-php-ext-install pdo_mysql bcmath
RUN pecl install redis && docker-php-ext-enable redis

# 运行阶段
FROM php:7.4-fpm-alpine
COPY --from=builder /usr/local/etc/php/conf.d/ /usr/local/etc/php/conf.d/
COPY --from=builder /usr/local/lib/php/extensions/ /usr/local/lib/php/extensions/
COPY . /var/www/html
RUN docker-php-ext-enable redis
```

用 Alpine 基础镜像，最终镜像从 800MB 降到 150MB。

## 五、资源限制

K8s Pod 资源请求和限制：

```yaml
resources:
  requests:
    cpu: "500m"
    memory: "512Mi"
  limits:
    cpu: "1000m"
    memory: "1Gi"
```

- CPU limit 不要设太低，PHP-FPM 是 CPU 密集型，限制太严会导致请求排队
- 内存 limit 要和 PHP-FPM max_children 匹配，防止 OOM

## 六、效果对比

| 指标 | 调优前 | 调优后 | 提升 |
|------|--------|--------|------|
| 单 Pod QPS | 200 | 800 | 300% |
| P99 延迟 | 800ms | 200ms | 75%↓ |
| Opcache 命中率 | 60% | 96% | - |
| 镜像大小 | 800MB | 150MB | 81%↓ |
| 502 错误率 | 5% | 0.1% | 98%↓ |

## 七、总结

K8s 环境下 PHP-FPM 调优核心：

1. **进程数匹配资源**：根据单进程内存和 Pod 内存限制算 max_children，不是越大越好
2. **static 模式**：固定进程数，避免动态创建开销
3. **Opcache 关闭时间戳检查**：生产环境代码通过镜像发布，不需要自动刷新
4. **预加载**：PHP 7.4+ 用 preload 预加载核心类
5. **镜像精简**：Alpine + 多阶段构建，减小镜像体积
6. **资源限制合理**：CPU 和内存 limit 要和 PHP-FPM 配置匹配

PHP-FPM 在容器里的调优和物理机思路一样，但要更注意资源限制和进程数的匹配。容器资源是隔离的，超了就 OOM，不能像物理机那样"超用一点没关系"。
