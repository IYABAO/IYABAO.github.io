---
title: "PHP 7.4 升级踩坑实录：从 7.2 到 7.4 的兼容性改造与性能收益"
date: 2020-11-22T15:40:00+08:00
draft: false
tags: ["PHP", "升级迁移", "性能优化", "兼容性", "Yii2"]
categories: ["PHP开发"]
summary: "生产环境 PHP 从 7.2 升级到 7.4 的完整过程，兼容性问题排查、代码改造、性能对比，以及升级过程中踩过的坑和解决方案。"
---

我们的招聘平台后端一直跑在 PHP 7.2 上，2020年下半年决定升级到 PHP 7.4。7.4 带来了预加载（OPcache Preloading）、类型属性、箭头函数等新特性，性能也有提升。但升级过程踩了不少坑，今天把完整过程记录下来。

## 一、为什么要升级

升级的动机：

1. **性能提升**：PHP 7.4 比 7.2 快约 10-15%，官方基准测试显示 WordPress 场景下快 20%+
2. **新特性**：类型属性、箭头函数、空合并赋值运算符、数字字面量分隔符等
3. **预加载（Preloading）**：OPcache 预加载可以把常用类加载到共享内存，请求时不用再加载，性能提升明显
4. **安全支持**：PHP 7.2 已经停止官方安全更新，7.4 还有安全支持
5. **依赖升级**：一些新的 Composer 包要求 PHP 7.4+，不升用不了

## 二、升级前准备

### 2.1 环境梳理

先梳理生产环境的 PHP 扩展和配置：

```bash
# 已安装的扩展
php -m

# 配置文件
php --ini

# 关键配置
php -i | grep -E "memory_limit|max_execution_time|upload_max_filesize|opcache"
```

我们的环境用了这些扩展：
- 核心：mbstring, pdo_mysql, mysqli, gd, curl, openssl, json
- 缓存：redis, apcu, opcache
- 其他：xdebug（开发环境）, imagick, bcmath, soap

### 2.2 兼容性检查

用 PHP_CodeSniffer 检查代码兼容性：

```bash
# 安装
composer require --dev phpcompatibility/php-compatibility

# 检查 7.4 兼容性
./vendor/bin/phpcs --standard=PHPCompatibility --runtime-set testVersion 7.4 --extensions=php /path/to/src
```

这个工具能静态分析代码，找出不兼容的用法。我们扫出来几十个问题，主要是：
- 废弃的函数（如 `each()`）
- 类型不兼容的用法
- 保留字用作类名/方法名

### 2.3 测试环境搭建

先在测试环境装 PHP 7.4，和生产环境配置一致，跑完整的测试用例：

```bash
# Ubuntu 安装 PHP 7.4
sudo apt-get install software-properties-common
sudo add-apt-repository ppa:ondrej/php
sudo apt-get update
sudo apt-get install php7.4 php7.4-fpm php7.4-mysql php7.4-redis php7.4-gd php7.4-curl php7.4-mbstring php7.4-xml php7.4-bcmath php7.4-soap php7.4-imagick php7.4-apcu
```

## 三、兼容性问题与改造

### 3.1 废弃函数 each()

PHP 7.2 开始废弃 `each()`，7.4 里还能用但会报 Notice。我们的老代码里有几处用了 `each()` 遍历数组：

```php
// 废弃写法
while (list($key, $val) = each($array)) {
    // ...
}

// 改为 foreach
foreach ($array as $key => $val) {
    // ...
}
```

### 3.2 类型属性与构造函数

PHP 7.4 支持类型属性，但如果属性有类型声明，未初始化时访问会报错：

```php
class User
{
    public int $id; // 类型属性
    public string $name;
}

$user = new User();
echo $user->id; // Error: Typed property User::$id must not be accessed before initialization
```

我们的代码里有些模型类属性没初始化就访问，加了默认值或在构造函数里初始化：

```php
class User
{
    public int $id = 0;
    public string $name = '';
}
```

### 3.3 数组访问中的花括号

PHP 7.4 废弃了用花括号访问数组和字符串偏移：

```php
// 废弃写法
$first = $str{0};
$value = $arr{0};

// 改为方括号
$first = $str[0];
$value = $arr[0];
```

老代码里有几处用了花括号访问，全局替换掉。

### 3.4 嵌套三元运算符

PHP 7.4 开始，嵌套三元运算符必须用括号明确优先级：

```php
// 7.4 之前可以（但不推荐）
$result = $a ? $b : $c ? $d : $e;

// 7.4 必须加括号
$result = $a ? $b : ($c ? $d : $e);
```

不加括号会报解析错误。我们代码里有一处嵌套三元，加了括号。

### 3.5 数字格式

PHP 7.4 之前，数字前面的 `0b`、`0x`、`0` 等前缀后面可以有空白字符，7.4 不允许了：

```php
// 7.4 之前可以
$num = 0x 1F;

// 7.4 必须连写
$num = 0x1F;
```

这个问题比较少见，我们代码里没有。

### 3.6 扩展兼容性

升级后检查每个扩展是否有 7.4 版本：

- `redis`：需要 5.0+ 版本
- `imagick`：需要 3.4.4+ 版本
- `apcu`：需要 5.1.18+ 版本
- `xdebug`：需要 2.8+ 版本

有几个扩展版本太低，升级到了兼容 7.4 的版本。

### 3.7 Yii2 框架兼容性

我们用的 Yii2 版本是 2.0.15，这个版本对 PHP 7.4 有兼容性问题。升级到了 Yii2 2.0.32：

```bash
composer update yiisoft/yii2 yiisoft/yii2-composer --with-dependencies
```

Yii2 2.0.32 修复了 PHP 7.4 的兼容性问题，主要是：
- `array_merge` 的参数类型
- `ReflectionType` 的用法变化
- 废弃函数的替换

## 四、OPcache 预加载配置

PHP 7.4 的预加载（Preloading）是个大杀器，可以把常用类预加载到共享内存，请求时不用再加载和编译，性能提升明显。

### 4.1 预加载配置

`php.ini`：

```ini
opcache.enable=1
opcache.enable_cli=0
opcache.memory_consumption=256
opcache.interned_strings_buffer=16
opcache.max_accelerated_files=20000
opcache.validate_timestamps=1
opcache.revalidate_freq=60
opcache.save_comments=1
opcache.fast_shutdown=1

# 预加载配置
opcache.preload=/var/www/api/preload.php
opcache.preload_user=www-data
```

### 4.2 预加载脚本

`preload.php`：

```php
<?php
// 预加载 Yii2 框架核心类
$yiiPath = '/var/www/api/vendor/yiisoft/yii2';

$iterator = new RecursiveIteratorIterator(
    new RecursiveDirectoryIterator($yiiPath)
);

foreach ($iterator as $file) {
    if ($file->getExtension() === 'php') {
        require_once $file->getPathname();
    }
}

// 预加载常用的业务类
$commonPaths = [
    '/var/www/api/common/models',
    '/var/www/api/common/services',
    '/var/www/api/common/helpers',
];

foreach ($commonPaths as $path) {
    $iterator = new RecursiveIteratorIterator(
        new RecursiveDirectoryIterator($path)
    );
    foreach ($iterator as $file) {
        if ($file->getExtension() === 'php') {
            require_once $file->getPathname();
        }
    }
}
```

预加载的注意事项：
- 预加载的类在请求中不能被覆盖，所以不能预加载会被修改的类
- 预加载脚本在 PHP-FPM 启动时执行，需要重启 PHP-FPM 才能生效
- 预加载太多类会增加内存占用，要权衡
- 预加载的类如果有依赖，要确保依赖也被预加载或能自动加载

### 4.3 预加载效果

开启预加载后，我们的接口平均响应时间从 80ms 降到了 55ms，提升约 30%。主要是框架核心类和常用业务类不用每次请求都加载编译了。

## 五、性能对比

升级前后在测试环境做了性能对比，用 ab 压测核心接口：

```bash
# 压测职位列表接口
ab -n 10000 -c 100 https://test.example.com/api/v1/jobs
```

| 指标 | PHP 7.2 | PHP 7.4 | 提升 |
|------|---------|---------|------|
| QPS | 850 | 1020 | +20% |
| 平均响应时间 | 117ms | 98ms | -16% |
| P99 响应时间 | 350ms | 280ms | -20% |
| 内存占用（单进程） | 65MB | 58MB | -11% |
| CPU 使用率（峰值） | 78% | 65% | -17% |

开启 OPcache 预加载后：

| 指标 | PHP 7.4（无预加载） | PHP 7.4（预加载） | 提升 |
|------|---------------------|-------------------|------|
| QPS | 1020 | 1280 | +25% |
| 平均响应时间 | 98ms | 78ms | -20% |

综合下来，PHP 7.2 → PHP 7.4 + 预加载，QPS 从 850 提升到 1280，提升 50%+。这个收益还是很可观的。

## 六、灰度发布

生产环境升级不能一刀切，我们用了灰度发布：

### 6.1 双版本并存

Nginx  upstream 配置两个 PHP-FPM 版本：

```nginx
upstream php72 {
    server unix:/run/php/php7.2-fpm.sock;
}

upstream php74 {
    server unix:/run/php/php7.4-fpm.sock;
}

# 默认走 7.2
location ~ \.php$ {
    fastcgi_pass php72;
    # ...
}

# 灰度路径走 7.4
location ~ ^/api/v1/jobs {
    fastcgi_pass php74;
    # ...
}
```

先让几个核心接口走 7.4，观察一周没问题后逐步扩大范围。

### 6.2 按流量比例灰度

用 Nginx 的 split_clients 模块按比例分流：

```nginx
split_clients "${remote_addr}${request_id}" $php_version {
    10% php74;
    * php72;
}

location ~ \.php$ {
    fastcgi_pass $php_version;
}
```

先 10% 流量走 7.4，观察错误率和性能，没问题后逐步调到 30%、50%、100%。

### 6.3 监控指标

灰度期间重点监控：
- 错误率：5xx 错误是否增加
- 响应时间：P50/P99 是否变慢
- PHP-FPM 进程数：是否有进程异常退出
- 慢日志：是否有新的慢查询
- 内存使用：是否有内存泄漏

灰度了两周，确认 7.4 稳定后全量切换。

## 七、踩过的坑

**1. OPcache 预加载导致类无法重新定义**

预加载了一个基类，某个请求里动态 `require` 了同名的类，报 "Cannot redeclare class" 错误。预加载的类在共享内存里，不能被覆盖。解决：预加载脚本里只预加载确定不会被动态覆盖的核心类。

**2. 类型属性未初始化报错**

升级后某个模型类加了类型属性，但在某些场景下属性没赋值就被访问，报 "Typed property must not be accessed before initialization"。这个错误在 7.2 里不会出现（未初始化属性默认 null）。解决：给所有类型属性加默认值，或者在构造函数里初始化。

**3. Redis 扩展版本不兼容**

升级 PHP 7.4 后，旧的 redis 扩展（4.x）编译不通过。需要升级到 redis 扩展 5.0+。5.0 版本的 API 有少量变化，主要是 `Redis::SERIALIZER_*` 常量的位置变了，代码里要调整。

**4. Yii2 升级后行为变化**

Yii2 从 2.0.15 升级到 2.0.32，有一些行为变化：
- `ActiveRecord::save()` 的返回值在某些场景下变了
- `Validator` 的错误消息格式有调整
- `Query::where()` 的参数处理更严格了

升级后跑了一遍全量测试，修了十几个因为行为变化导致的测试失败。

**5. 内存泄漏误报**

升级后监控显示 PHP-FPM 进程内存缓慢增长，以为是内存泄漏。查了一圈发现是 OPcache 的 `interned_strings_buffer` 设太大了（64MB），每个进程都共享这块内存，但监控工具把共享内存算到了每个进程头上。调到 16MB 后正常。

**6. 短标签问题**

PHP 7.4 里 `<?=` 短输出标签始终可用，但 `<?` 短标签需要 `short_open_tag=On`。我们有个老文件用了 `<?` 短标签，测试环境开了 short_open_tag 没发现，生产环境没开，上线后报 500。全局搜了一遍把 `<?` 都改成了 `<?php`。

## 八、总结

PHP 7.2 升级到 7.4 的完整流程：

1. **准备阶段**：环境梳理、兼容性静态检查、测试环境搭建
2. **改造阶段**：修复废弃函数、类型属性初始化、扩展升级、框架升级
3. **优化阶段**：配置 OPcache 预加载，性能调优
4. **验证阶段**：全量测试、性能对比、安全检查
5. **发布阶段**：灰度发布、监控观察、全量切换

核心经验：
- 升级前一定要用 PHP_CodeSniffer 做兼容性静态检查，能提前发现大部分问题
- 框架和扩展版本要确认兼容 7.4，不兼容的先升级
- OPcache 预加载是 7.4 的大杀器，性能提升明显，但要注意预加载的类不能被覆盖
- 灰度发布是必须的，不要一刀切，出问题能快速回滚
- 升级后要观察至少一周，确认没有内存泄漏、错误率上升等问题

升级完成后，性能提升 50%+，还能用 7.4 的新特性，后续维护也更方便。PHP 版本升级虽然有风险，但收益是值得的。建议大家定期跟进 PHP 版本，不要等版本停止支持了才被迫升级，那时候跨度更大，风险更高。
