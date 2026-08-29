---
title: "招聘通统计分析后台架构：从单表查询到独立统计服务的演进之路"
date: 2020-02-26T10:15:00+08:00
draft: false
tags: ["架构演进", "数据分析", "PHP", "MySQL", "异步处理"]
categories: ["架构设计"]
summary: "招聘通统计分析后台从单表实时查询到独立统计服务的架构演进，解决大数据量下多维统计查询慢、影响主库性能的问题。"
---

招聘通是我们平台的核心产品之一，企业端用它管理简历、发布职位、查看招聘效果。统计分析模块是企业用户最常用的功能之一，查看职位浏览量、简历投递数、面试转化率等数据。

这个模块最早是直接在业务库里做实时查询，数据量上来之后问题不断。后来重构为独立的统计服务，性能和稳定性都上了一个台阶。今天把整个演进过程记录下来。

## 一、原始方案：单表实时查询

最早的统计分析很简单，直接在业务表上做 COUNT 和 SUM：

```php
public function actionJobStats()
{
    $companyId = Yii::$app->user->company_id;
    $startDate = Yii::$app->request->get('start_date');
    $endDate = Yii::$app->request->get('end_date');

    // 职位浏览量
    $views = (new Query())
        ->from('job_view_log')
        ->where(['company_id' => $companyId])
        ->andWhere(['between', 'created_at', strtotime($startDate), strtotime($endDate)])
        ->count();

    // 简历投递数
    $applies = (new Query())
        ->from('job_apply')
        ->where(['company_id' => $companyId])
        ->andWhere(['between', 'created_at', strtotime($startDate), strtotime($endDate)])
        ->count();

    // 面试数
    $interviews = (new Query())
        ->from('interview')
        ->where(['company_id' => $companyId])
        ->andWhere(['between', 'created_at', strtotime($startDate), strtotime($endDate)])
        ->count();

    return [
        'views' => $views,
        'applies' => $applies,
        'interviews' => $interviews,
        'apply_rate' => $views > 0 ? round($applies / $views * 100, 2) : 0,
        'interview_rate' => $applies > 0 ? round($interviews / $applies * 100, 2) : 0,
    ];
}
```

数据量小的时候没问题，查询几百毫秒就返回。但随着业务增长，问题来了：

### 1.1 问题一：查询慢

`job_view_log` 表到了 5000 万行，按公司和时间范围统计，一次查询要 3-5 秒。用户选个时间范围，页面转半天圈，体验很差。

### 1.2 问题二：影响主库

统计查询都打在主库上，和业务查询抢资源。大公司用户查统计的时候，正好赶上投递高峰期，主库 CPU 飙到 90%，业务接口也跟着慢。

### 1.3 问题三：维度扩展难

业务方要求加更多统计维度：按职位、按渠道、按天趋势。每加一个维度就要写一堆查询，代码越来越臃肿。而且多维组合查询更慢，有的要十几秒。

## 二、第一阶段优化：读库分离 + 预聚合表

先做了两个紧急优化，缓解线上压力。

### 2.1 读库分离

把统计查询全部切到从库，不打主库。MySQL 主从复制有延迟，但统计数据对实时性要求不高，延迟几秒完全可以接受。

```php
// 统计查询用从库
$db = Yii::$app->dbSlave;
$views = (new Query())
    ->from('job_view_log')
    ->where(['company_id' => $companyId])
    ->andWhere(['between', 'created_at', $start, $end])
    ->count($db);
```

这个改动最简单，效果也最明显——主库压力立刻降下来了。但查询慢的问题没解决，从库查一样慢。

### 2.2 预聚合表

按天 + 公司维度做预聚合，每天凌晨把前一天的数据统计好存起来：

```sql
CREATE TABLE `stats_daily_company` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `company_id` int(11) NOT NULL,
  `date` date NOT NULL,
  `views` int(11) NOT NULL DEFAULT '0',
  `applies` int(11) NOT NULL DEFAULT '0',
  `interviews` int(11) NOT NULL DEFAULT '0',
  `offers` int(11) NOT NULL DEFAULT '0',
  PRIMARY KEY (`id`),
  UNIQUE KEY `company_date` (`company_id`,`date`),
  KEY `date` (`date`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

定时任务每天凌晨跑：

```php
public function actionAggregateDaily()
{
    $yesterday = date('Y-m-d', strtotime('-1 day'));
    $start = strtotime($yesterday . ' 00:00:00');
    $end = strtotime($yesterday . ' 23:59:59');

    // 按公司统计浏览量
    $viewStats = (new Query())
        ->select(['company_id', 'COUNT(*) as cnt'])
        ->from('job_view_log')
        ->where(['between', 'created_at', $start, $end])
        ->groupBy('company_id')
        ->all();

    foreach ($viewStats as $stat) {
        $this->upsertDailyStats($stat['company_id'], $yesterday, ['views' => $stat['cnt']]);
    }

    // 同理统计投递、面试等
    // ...
}
```

查询的时候直接读预聚合表：

```php
$stats = (new Query())
    ->select(['SUM(views) as views', 'SUM(applies) as applies', 'SUM(interviews) as interviews'])
    ->from('stats_daily_company')
    ->where(['company_id' => $companyId])
    ->andWhere(['between', 'date', $startDate, $endDate])
    ->one();
```

预聚合表只有几百万行，查询几十毫秒就返回。性能提升非常明显。

### 2.3 预聚合的局限

预聚合表解决了按天 + 公司维度的统计，但还有问题：

1. **维度不够**：业务方要按职位、按渠道统计，预聚合表覆盖不了
2. **实时性差**：T+1 更新，当天的数据看不到，用户不满意
3. **历史数据修正麻烦**：如果某天的数据算错了，要重跑那天的聚合，还要检查关联数据

## 三、第二阶段：独立统计服务

预聚合表用了一年多，业务方的需求越来越多，预聚合表加了一张又一张，维护成本很高。2020年初决定重构，做独立的统计服务。

### 3.1 架构设计

```text
业务系统 → 发消息到 Kafka → 统计服务消费 → 写入 ClickHouse
                              ↓
                        实时聚合（Redis）
                              ↓
统计查询 API ← 读 ClickHouse / Redis
```

核心思路：
1. **数据采集**：业务系统的关键操作（浏览、投递、面试等）发事件到 Kafka
2. **数据存储**：统计服务消费 Kafka，写入 ClickHouse（列式存储，适合多维分析）
3. **实时聚合**：当天的实时数据用 Redis 做增量聚合
4. **查询服务**：独立的统计 API，读 ClickHouse + Redis，不碰业务库

### 3.2 为什么选 ClickHouse

对比了几个方案：
- **MySQL**：预聚合表已经证明不够灵活，多维查询还是慢
- **Elasticsearch**：适合全文检索，聚合查询性能不如 ClickHouse，存储成本高
- **ClickHouse**：列式存储，向量化执行，多维聚合查询极快，单机就能扛亿级数据

ClickHouse 最打动我的是查询速度。同样的多维聚合查询，MySQL 要 10 秒，ClickHouse 200 毫秒。而且不需要预聚合，任意维度组合都能实时查。

### 3.3 事件数据模型

ClickHouse 的表结构：

```sql
CREATE TABLE stats.events (
    event_id String,
    event_type String,       -- view, apply, interview, offer
    company_id Int32,
    job_id Int32,
    user_id Int32,
    channel String,          -- pc, app, miniprogram
    city_id Int32,
    created_at DateTime
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(created_at)
ORDER BY (company_id, event_type, created_at)
TTL created_at + INTERVAL 2 YEAR;
```

按月份分区，按公司 + 事件类型 + 时间排序，查询时能快速定位到相关数据。

### 3.4 实时数据处理

当天的实时数据用 Redis 做增量计数，避免每次查询都扫 ClickHouse 的当天分区：

```php
// 消费 Kafka 消息，更新 Redis 实时计数
$key = "stats:realtime:{$companyId}:{$eventType}:{$date}";
$redis->incr($key);

// 同时异步写入 ClickHouse
$clickhouse->insert('stats.events', $eventData);
```

查询时合并实时数据和历史数据：

```php
public function queryStats($companyId, $startDate, $endDate, $dimensions = [])
{
    $today = date('Y-m-d');
    $result = [];

    // 历史数据查 ClickHouse
    if ($startDate < $today) {
        $histEnd = min($endDate, date('Y-m-d', strtotime('-1 day')));
        $result = $this->clickhouseQuery($companyId, $startDate, $histEnd, $dimensions);
    }

    // 当天数据查 Redis
    if ($endDate >= $today) {
        $realtime = $this->redisQuery($companyId, $today, $dimensions);
        $result = $this->mergeStats($result, $realtime);
    }

    return $result;
}
```

### 3.5 查询 API

独立的统计服务，对外提供 RESTful API：

```
GET /api/stats/overview?company_id=123&start_date=2020-01-01&end_date=2020-01-31
GET /api/stats/trend?company_id=123&start_date=2020-01-01&end_date=2020-01-31&dimension=day
GET /api/stats/by-job?company_id=123&start_date=2020-01-01&end_date=2020-01-31
GET /api/stats/by-channel?company_id=123&start_date=2020-01-01&end_date=2020-01-31
```

业务系统调用统计 API，不直接查数据库。彻底解耦。

## 四、效果对比

| 指标 | 原始方案 | 预聚合表 | 独立统计服务 |
|------|---------|---------|------------|
| 概览查询响应 | 3-5秒 | 50ms | 30ms |
| 按天趋势查询 | 10-15秒 | 200ms | 80ms |
| 按职位统计 | 不支持 | 需加表 | 100ms |
| 按渠道统计 | 不支持 | 需加表 | 80ms |
| 数据实时性 | 实时 | T+1 | 实时 |
| 对主库影响 | 大 | 小 | 无 |

## 五、踩过的坑

**1. Kafka 消息丢失**

早期用 Kafka 的时候没做幂等，消费者处理失败后消息丢了，统计数据对不上。后来加了消息重试 + 死信队列，处理失败的消息进死信队列，人工排查后重放。

**2. ClickHouse 写入太频繁**

每条事件都单独写 ClickHouse，写入 QPS 太高，ClickHouse 扛不住。改成批量写入，攒够 1000 条或等 5 秒写一次，写入性能提升了 10 倍。

**3. 实时数据和历史数据重复**

凌晨跑批把前一天的 Redis 数据导入 ClickHouse 后，没有清 Redis，导致第二天查前一天的数据时，Redis 和 ClickHouse 都有，统计重复了。加了导入后自动清 Redis 的逻辑解决。

**4. 维度爆炸**

业务方不停加维度，按职位、按渠道、按城市、按学历、按经验... 维度多了之后，Redis 的 key 数量爆炸，内存不够用。后来改成只对高频维度做实时聚合，低频维度直接查 ClickHouse（当天数据量不大，ClickHouse 查也很快）。

## 六、总结

招聘通统计分析后台的架构演进，经历了三个阶段：

1. **单表实时查询**：简单直接，数据量小的时候够用，大了之后慢且影响主库
2. **预聚合表**：用空间换时间，性能提升明显，但维度扩展难、实时性差
3. **独立统计服务**：ClickHouse + Kafka + Redis，支持任意维度实时查询，和业务系统彻底解耦

核心经验：
- 统计查询一定要和业务库隔离，不能打主库
- 预聚合是简单有效的方案，但要评估维度扩展性
- ClickHouse 做多维统计真的强，单机就能扛亿级数据
- 实时数据用 Redis 增量聚合，历史数据查 ClickHouse，两者合并
- 数据一致性是统计系统的生命线，幂等、重试、对账一个都不能少

这个统计服务现在还在跑，支撑了招聘通、最佳东方等多个产品线的统计需求。架构上留了扩展空间，加新维度、新指标不用动核心架构。技术选型上，ClickHouse 是这次重构最正确的决定，性能远超预期。
