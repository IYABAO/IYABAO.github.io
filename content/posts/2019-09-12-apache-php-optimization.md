---
title: "Apache 服务器专项调优：从 MPM 模式到 Opcache 的全链路优化"
date: 2019-09-12T16:10:00+08:00
draft: false
tags: ["Apache", "PHP", "性能调优", "Opcache", "运维"]
categories: ["运维"]
summary: "Apache + PHP 服务器性能调优实战，从 MPM 模式选择、进程数配置到 Opcache 优化，完整记录调优前后的性能对比。"
---

早年做跨境电商项目，服务器跑在 AWS 上，Apache + PHP 的经典组合。流量上来之后服务器经常 504，排查了一圈发现是 Apache 配置和 PHP 运行模式的问题。今天把那次调优的完整过程记录下来，给还在用 Apache + PHP 的朋友做个参考。

## 一、问题现象

项目是雅宝路中俄跨境电商平台，跑在 AWS 小型集群上，前端 Apache，后端 PHP + MySQL。大促期间 QPS 到 500 左右就开始大量 504，服务器 load average 飙到 20+。

先看了下 Apache 的错误日志：

```
[Fri Sep 06 14:23:15 2019] [error] server reached MaxRequestWorkers setting, consider raising the MaxRequestWorkers setting
```

很明显，Apache 的 worker 数不够用了。但这只是表象，直接调大 MaxRequestWorkers 可能会让问题更严重——内存不够用导致 OOM。

## 二、MPM 模式选择

Apache 有三种 MPM（Multi-Processing Module）模式：prefork、worker、event。

### 2.1 三种模式对比

| 模式 | 进程模型 | 线程模型 | PHP 兼容性 | 适用场景 |
|------|---------|---------|-----------|---------|
| prefork | 多进程 | 无线程 | 最好（非线程安全） | 稳定优先，低并发 |
| worker | 多进程 | 多线程 | 需要 ZTS 版本 | 中高并发 |
| event | 多进程 | 多线程 + 异步 | 需要 ZTS 版本 | 高并发，长连接多 |

我们的项目用的是 mod_php，PHP 是非线程安全版本，所以只能用 prefork 模式。这也是性能瓶颈的根源之一——prefork 每个请求占一个进程，进程创建和销毁的开销大，内存占用也高。

### 2.2 prefork 模式配置

先看当前配置：

```apache
<IfModule mpm_prefork_module>
    StartServers          5
    MinSpareServers       5
    MaxSpareServers      10
    MaxRequestWorkers    150
    MaxConnectionsPerChild   0
</IfModule>
```

`MaxRequestWorkers` 只有 150，QPS 500 的情况下肯定不够。但直接调大之前，得先算一下内存够不够。

### 2.3 计算合理的 MaxRequestWorkers

先看单个 Apache 进程的内存占用：

```bash
ps -ylC httpd --sort:rss | awk '{sum+=$8; ++n} END {print "平均内存: " sum/n/1024 " MB"}'
```

我们的环境单个 httpd 进程大约占 80MB（因为 mod_php 把 PHP 解释器嵌进去了）。服务器内存 8GB，系统和 MySQL 占了 3GB，留给 Apache 的大约 4GB。

```
MaxRequestWorkers = 4GB / 80MB ≈ 50
```

等等，这不对，当前配置是 150，但实际内存没爆。因为不是所有进程都同时在处理请求，空闲进程的内存占用会低一些。实际峰值时同时活跃的进程数大约是 80-100。

合理的配置应该是：

```apache
<IfModule mpm_prefork_module>
    StartServers          10
    MinSpareServers      10
    MaxSpareServers      20
    MaxRequestWorkers    256
    MaxConnectionsPerChild  1000
</IfModule>
```

关键点：
- `StartServers` 调高到 10，避免启动后瞬间创建进程的开销
- `MaxRequestWorkers` 调到 256，留一定余量，但不能超过内存承载能力
- `MaxConnectionsPerChild` 设为 1000，每个进程处理 1000 个请求后自动重启，防止内存泄漏

`MaxConnectionsPerChild` 这个参数很重要。PHP 有内存泄漏的老问题，长时间运行的进程内存会慢慢涨，设个上限自动回收是最稳妥的方案。

## 三、PHP-FPM 模式迁移

prefork + mod_php 的组合内存占用太高，后来我们迁移到了 Apache + PHP-FPM 的模式。PHP-FPM 是独立的进程池，Apache 只负责处理 HTTP 请求，PHP 解析交给 FPM。

### 3.1 配置 Apache 使用 FastCGI

```apache
# 禁用 mod_php，启用 mod_proxy_fcgi
a2dismod php5
a2enmod proxy_fcgi

# 虚拟主机配置
<VirtualHost *:80>
    ServerName example.com
    DocumentRoot /var/www/html

    <FilesMatch \.php$>
        SetHandler "proxy:unix:/run/php/php7.0-fpm.sock|fcgi://localhost/"
    </FilesMatch>
</VirtualHost>
```

### 3.2 PHP-FPM 进程池配置

```ini
[www]
user = www-data
group = www-data
listen = /run/php/php7.0-fpm.sock
listen.owner = www-data
listen.group = www-data

pm = dynamic
pm.max_children = 50
pm.start_servers = 10
pm.min_spare_servers = 5
pm.max_spare_servers = 20
pm.max_requests = 1000

slowlog = /var/log/php-fpm/slow.log
request_slowlog_timeout = 3s
```

PHP-FPM 的进程数计算和 Apache 类似，但单个 FPM 进程的内存占用比 mod_php 低一些（大约 50-60MB），因为不需要加载 Apache 的模块。

`pm.max_requests = 1000` 和 Apache 的 `MaxConnectionsPerChild` 同理，防止内存泄漏。

`slowlog` 和 `request_slowlog_timeout` 是排查慢请求的利器，超过 3 秒的请求会记录调用栈，能快速定位性能瓶颈。

### 3.3 迁移后的效果

迁移到 PHP-FPM 后：
- 单个 Apache 进程内存从 80MB 降到 15MB（只处理静态资源和反向代理）
- 同样 4GB 内存，Apache 可以跑到 200+ 并发连接
- PHP-FPM 进程池独立管理，PHP 崩溃不影响 Apache
- 整体 QPS 承载能力从 500 提升到 1200+

## 四、Opcache 优化

PHP 是解释型语言，每次请求都要重新编译 PHP 脚本为 opcode 再执行。Opcache 把编译后的 opcode 缓存到共享内存，避免重复编译，性能提升非常明显。

### 4.1 Opcache 配置

```ini
[opcache]
opcache.enable=1
opcache.enable_cli=0
opcache.memory_consumption=256
opcache.interned_strings_buffer=16
opcache.max_accelerated_files=10000
opcache.max_wasted_percentage=10
opcache.revalidate_freq=60
opcache.validate_timestamps=1
opcache.save_comments=1
opcache.fast_shutdown=1
```

关键参数解释：
- `memory_consumption=256`：Opcache 共享内存大小，项目大的话给 256MB
- `max_accelerated_files=10000`：最多缓存多少个 PHP 文件，要大于项目文件总数
- `revalidate_freq=60`：多少秒检查一次文件是否更新，生产环境可以设大一些
- `validate_timestamps=1`：是否检查文件更新时间，开发环境必须开，生产环境可以关

### 4.2 验证 Opcache 生效

写个 `opcache.php` 查看状态：

```php
<?php
$status = opcache_get_status();
echo "已缓存文件数: " . $status['opcache_statistics']['num_cached_scripts'] . "\n";
echo "命中率: " . round($status['opcache_statistics']['opcache_hit_rate'], 2) . "%\n";
echo "内存使用: " . round($status['memory_usage']['used_memory'] / 1024 / 1024, 2) . " MB\n";
echo "内存剩余: " . round($status['memory_usage']['free_memory'] / 1024 / 1024, 2) . " MB\n";
```

命中率应该在 95% 以上才正常。如果命中率低，可能是 `max_accelerated_files` 不够，或者 `revalidate_freq` 太短。

### 4.3 Opcache 踩坑

**1. 代码更新不生效**

生产环境如果 `validate_timestamps=0`，代码更新后 Opcache 不会自动刷新，需要重启 PHP-FPM 或者调用 `opcache_reset()`。我们的发布流程里加了一步：发布完成后调用 `opcache_reset()` 清缓存。

**2. 内存不足导致缓存失效**

`memory_consumption` 设太小，Opcache 内存满了之后会清空所有缓存重新开始，命中率会骤降。一定要根据项目大小给足够的内存。

**3. CLI 模式不要开 Opcache**

`opcache.enable_cli=0`，CLI 模式下每次执行都是独立进程，Opcache 没有意义，反而占内存。

## 五、其他优化项

### 5.1 Apache 配置优化

```apache
# 关闭不需要的模块
a2dismod autoindex cgi env negotiation status

# 开启 gzip 压缩
<IfModule mod_deflate.c>
    AddOutputFilterByType DEFLATE text/html text/plain text/css application/json application/javascript text/xml application/xml
</IfModule>

# 静态资源缓存
<IfModule mod_expires.c>
    ExpiresActive On
    ExpiresByType image/jpg "access plus 1 year"
    ExpiresByType image/png "access plus 1 year"
    ExpiresByType text/css "access plus 1 month"
    ExpiresByType application/javascript "access plus 1 month"
</IfModule>

# 隐藏 Apache 版本号
ServerTokens Prod
ServerSignature Off
```

### 5.2 PHP 配置优化

```ini
; 内存限制
memory_limit = 256M

; 上传限制
upload_max_filesize = 20M
post_max_size = 20M

; 执行时间
max_execution_time = 30
max_input_time = 60

; 错误日志
log_errors = On
error_log = /var/log/php/error.log

; 关闭 display_errors
display_errors = Off
```

### 5.3 MySQL 连接优化

PHP 应用里 MySQL 连接池很重要。用 PDO 持久连接或者中间件（如 ProxySQL）减少连接创建开销：

```php
// PDO 持久连接
$pdo = new PDO($dsn, $user, $pass, [
    PDO::ATTR_PERSISTENT => true,
    PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
]);
```

但持久连接要小心事务和连接状态泄漏，使用不当会出诡异的问题。我们后来用了 ProxySQL 做连接池，更稳定。

## 六、调优前后对比

| 指标 | 调优前 | 调优后 | 提升 |
|------|--------|--------|------|
| 最大 QPS | 500 | 1200+ | 140% |
| P99 延迟 | 1200ms | 350ms | 71%↓ |
| 内存使用率 | 85% | 65% | 20%↓ |
| 504 错误率 | 5% | 0.1% | 98%↓ |
| Opcache 命中率 | 未开启 | 97% | - |

## 七、总结

Apache + PHP 的性能调优，核心就几个点：

1. **MPM 模式选对**：prefork 配 mod_php 简单但内存占用高；PHP-FPM 模式更灵活，资源利用率更高
2. **进程数算清楚**：根据内存和单进程占用计算合理的 MaxRequestWorkers / max_children，不是越大越好
3. **Opcache 必开**：PHP 性能提升最明显的手段，没有之一，命中率要保证 95%+
4. **防止内存泄漏**：MaxConnectionsPerChild / max_requests 设上限，进程自动回收
5. **静态资源优化**：gzip 压缩 + 浏览器缓存，减少动态请求压力

这套方案虽然是几年前的经验，但 Apache + PHP 的组合现在还有很多团队在用，核心原理是相通的。后来迁移到 Nginx + PHP-FPM 后，性能又上了一个台阶，但 Apache 的调优经验帮我打下了扎实的基础。

性能调优是个持续的过程，没有终点。每次业务迭代、数据量增长，都可能带来新的瓶颈。保持对监控数据的敏感，定期 review，是每个后端工程师的基本功。
