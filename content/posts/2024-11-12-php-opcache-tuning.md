---
title: "PHP Opcache 调优：从命中率 80% 到 99%"
date: 2024-11-12T09:00:00+08:00
lastmod: 2024-11-12T09:00:00+08:00
draft: false
author: IYABAO
tags:
  - PHP
  - Opcache
  - 性能优化
categories:
  - 技术
summary: "Opcache 是 PHP 性能的第一杠杆：命中率 99% 和 80% 的差距是 3 倍吞吐。内存分配、max_accelerated_files、预热、K8s 冷启动——完整的 Opcache 调优手册。"
---

# PHP Opcache 调优：从命中率 80% 到 99%

PHP 每请求都要"解析源码 → 编译成字节码 → 执行"。Opcache 把编译好的字节码缓存进共享内存，**省掉了解析和编译两步**——这是 PHP 性能的第一杠杆。我把线上命中率从 80% 调到 99%，吞吐提升近 3 倍。

## 一、先看 Opcache 做了什么

```
没有 Opcache： 请求 → 读源码 → 词法分析 → 编译字节码 → 执行 → 释放（每次重复）
有 Opcache：   请求 → 读缓存字节码 → 执行（一次编译，永久复用）
```

**结论**：Opcache 生效时，PHP 请求省掉 30-60% 的 CPU（编译开销）。

## 二、核心配置

```ini
[opcache]
zend_extension=opcache.so
opcache.enable=1
opcache.enable_cli=1                # CLI 也开（cron 任务受益）
opcache.memory_consumption=256      # 共享内存大小（MB）
opcache.interned_strings_buffer=32  # 字符串驻留缓冲
opcache.max_accelerated_files=50000 # 缓存文件数上限
opcache.validate_timestamps=0       # 生产关掉 mtime 检查
opcache.revalidate_freq=0
opcache.fast_shutdown=1
opcache.opcache.file_cache=/tmp/opcache_file_cache  # 文件缓存兜底
```

## 三、两个关键决策

### 决策 1：memory_consumption 给多少

**不够**：新文件编译不进缓存，命中率下降，或强制驱逐旧缓存。

```bash
# 生产查看使用率
php -r "var_dump(opcache_get_status()['memory_usage']);"
# 看 memory_free 是否接近 0
```

**够用标准**：内存占用率 < 80%（留余量），命中率 > 98%。

### 决策 2：validate_timestamps 关不关

- **开（默认）**：每次请求 stat 文件 mtime → 代码热更新生效，但**每个请求多一次磁盘 stat**，高并发下是实打实的开销
- **关**：快，但改代码后不生效，需要手动清缓存

**生产（镜像发布）关掉**，开发环境开着。我们代码走 CI 构建镜像发布，文件不变，关掉是纯赚。

## 四、命中率怎么查

```bash
# 命令行查
php -r "
\$s = opcache_get_status();
echo '命中率: ' . round(\$s['opcache_statistics']['opcache_hit_rate'], 2) . '%';
echo '缓存文件: ' . \$s['opcache_statistics']['num_cached_scripts'] . '/' . \$s['opcache_statistics']['num_cached_keys'] . PHP_EOL;
"

# 或用 opcache-gui 网页版看
```

**命中率目标**：

- < 90%：有问题（内存不够 / max_files 不够 / 文件未预热）
- 90-97%：还可以
- **98%+：健康**

## 五、K8s 下的冷启动问题（最重要）

**我在《K8s 单 Pod 性能调优》里讲过**：Pod 重建 = Opcache 冷缓存，第一个请求要全量编译，30-60s 内吞吐崩。

### 解法：启动预热

```bash
# entrypoint：先预热再启动
php opcache_prewarm.php   # 遍历所有 PHP 文件，触发编译
php-fpm -F
```

```php
// opcache_prewarm.php
$files = getAllPhpFiles('/var/www');   // 递归收集
foreach ($files as $f) {
    if (opcache_compile_file($f)) {    // 预编译进共享内存
        $count++;
    }
}
echo "prewarmed: $count files\n";
```

**注意**：预热必须在**同一个容器/进程组**里做（Opcache 是进程共享内存），跨容器预热无效。

## 六、和 FPM worker 的配合

```
Opcache 共享内存（所有 worker 共享字节码）
  │
  ▼
PHP-FPM worker（只执行，不再编译）
```

**Opcache 内存不够时**，多个 worker 争抢会导致 miss 和驱逐——**Opcache 内存是全局的，别按 worker 数算**，按"全量字节码大小 × 1.5"给。

```bash
# 估算全量字节码大小
du -sh /var/www/vendor /var/www/app
# 经验：源码 500MB → 字节码约 150-200MB → memory_consumption=256 合适
```

## 七、效果数据

| 指标 | 调优前 | 调优后 |
|---|---|---|
| Opcache 命中率 | 80% | 99%+ |
| 单 Pod QPS | 120 | 320（+167%） |
| P99 延迟 | 380ms | 160ms |
| 编译导致的 CPU 峰值 | 明显 | 消失 |

## 八、踩坑记录

1. **max_accelerated_files 不够**：文件数超了，新文件不缓存 → 命中率莫名下降。用 `opcache_get_status()['opcache_statistics']['num_cached_keys']` 和文件总数对比
2. **CLI 没开**：cron 任务每次全量编译 → 大批定时任务 CPU 飙高。`enable_cli=1` 解决
3. **文件缓存目录权限**：`opcache.file_cache` 目录无权限 → 启动报错，静默降级
4. **和 opcache-recommended 冲突**：别乱装第三方"推荐配置"，以实际命中率为准

## 总结

Opcache 调优的核心：

1. **命中率是北极星指标**：一切配置以 98%+ 为目标
2. **内存够 + 文件数够**：两个"够"是基础
3. **生产关 mtime 校验**：镜像发布场景纯赚
4. **K8s 必做预热**：冷启动是容器时代的新坑

**Opcache 是 PHP 最便宜的优化**——不用改代码、不用加机器，配置对了吞吐翻倍。
