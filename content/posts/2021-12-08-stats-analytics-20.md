---
title: "招聘通统计分析 2.0：从实时查询到 OLAP 预聚合的性能跃迁"
date: 2021-12-08T10:30:00+08:00
draft: false
tags: ["OLAP", "预聚合", "数据分析", "ClickHouse", "PHP", "性能优化"]
categories: ["架构设计"]
summary: "招聘通统计分析 2.0 架构升级，从 MySQL 实时查询到 ClickHouse + 预聚合的 OLAP 方案，解决大数据量下多维统计查询慢的问题，查询性能提升 50 倍。"
keywords: ["统计分析", "OLAP", "预聚合", "性能优化", "报表"]
---

招聘通的统计分析模块 1.0 版本用的是 MySQL 实时查询 + 简单的按天预聚合表，随着数据量增长（行为日志到了 5 亿条），查询越来越慢，有的报表要等十几秒。2021年底做了 2.0 升级，引入 ClickHouse 做 OLAP 分析，配合多层预聚合，查询性能提升了 50 倍。今天把升级过程分享出来。

## 一、1.0 版本的问题

1.0 版本的架构：
- 明细数据存在 MySQL，按月份分表
- 常用统计（按天+公司）做了预聚合表
- 多维组合查询（按职位、按渠道、按城市）直接查明细表

问题：
1. **多维查询慢**：按职位+渠道+城市组合查询，要扫描几千万行，5-15秒
2. **预聚合表不够用**：维度组合太多，不可能为每种组合都建预聚合表
3. **MySQL 不适合 OLAP**：MySQL 是行存，适合事务处理，不适合大规模聚合分析
4. **扩展性差**：数据量再增长，MySQL 分表也扛不住

## 二、2.0 架构设计

### 2.1 整体架构

```
业务系统 → 双写（MySQL + Kafka）
                    ↓
              ClickHouse（明细数据）
                    ↓
              预聚合表（Materialized View）
                    ↓
              查询 API → 前端报表
```

- **数据采集**：业务系统写 MySQL 的同时发 Kafka，ClickHouse 消费 Kafka 写入明细
- **明细存储**：ClickHouse 存全量明细数据，支持任意维度实时查询
- **预聚合**：ClickHouse 的 Materialized View 自动维护预聚合表，高频查询走预聚合
- **查询服务**：统一查询 API，自动路由到预聚合表或明细表

### 2.2 为什么选 ClickHouse

对比了几个 OLAP 引擎：
- **Druid**：功能强，但部署复杂，资源消耗大
- **Presto/Trino**：查询引擎，需要搭配存储，不适合做预聚合
- **ClickHouse**：单机性能极强，列存+向量化执行，部署简单，支持 Materialized View

ClickHouse 最打动我的是单机性能——一台 8C32G 的机器就能扛亿级数据的多维查询，响应时间几百毫秒。而且支持 Materialized View，预聚合自动维护，不用自己写定时任务。

## 三、ClickHouse 表设计

### 3.1 明细表

```sql
CREATE TABLE stats.events (
    event_id String,
    event_type String,       -- view, apply, interview, download
    company_id Int32,
    job_id Int32,
    user_id Int32,
    channel String,          -- pc, app, miniprogram
    city_id Int32,
    source String,           -- search, recommend, direct
    created_at DateTime64(3)
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(created_at)
ORDER BY (company_id, event_type, created_at)
TTL created_at + INTERVAL 2 YEAR;
```

### 3.2 预聚合表（Materialized View）

按公司+天+事件类型预聚合：

```sql
CREATE TABLE stats.daily_company (
    company_id Int32,
    event_date Date,
    event_type String,
    pv AggregateFunction(count, String),
    uv AggregateFunction(uniq, Int32)
) ENGINE = AggregatingMergeTree()
PARTITION BY toYYYYMM(event_date)
ORDER BY (company_id, event_date, event_type);

-- Materialized View 自动同步
CREATE MATERIALIZED VIEW stats.daily_company_mv TO stats.daily_company AS
SELECT
    company_id,
    toDate(created_at) AS event_date,
    event_type,
    countState(event_id) AS pv,
    uniqState(user_id) AS uv
FROM stats.events
GROUP BY company_id, event_date, event_type;
```

按公司+职位+天预聚合：

```sql
CREATE TABLE stats.daily_job (
    company_id Int32,
    job_id Int32,
    event_date Date,
    event_type String,
    pv AggregateFunction(count, String),
    uv AggregateFunction(uniq, Int32)
) ENGINE = AggregatingMergeTree()
PARTITION BY toYYYYMM(event_date)
ORDER BY (company_id, job_id, event_date, event_type);

CREATE MATERIALIZED VIEW stats.daily_job_mv TO stats.daily_job AS
SELECT
    company_id, job_id,
    toDate(created_at) AS event_date,
    event_type,
    countState(event_id) AS pv,
    uniqState(user_id) AS uv
FROM stats.events
GROUP BY company_id, job_id, event_date, event_type;
```

关键点：
- `AggregatingMergeTree`：预聚合表用这个引擎，自动合并相同主键的聚合状态
- `countState`/`uniqState`：聚合函数的 State 版本，存储中间状态，查询时用 `countMerge`/`uniqMerge` 合并
- `Materialized View`：插入明细表时自动更新预聚合表，实时性好

## 四、查询服务

### 4.1 查询路由

查询时自动选择最优的表（预聚合表或明细表）：

```php
class StatsQueryService
{
    public function query($params)
    {
        // 根据查询维度选择预聚合表
        $dimensions = $this->getDimensions($params);
        
        if ($this->canUseDailyCompany($dimensions)) {
            return $this->queryFromDailyCompany($params);
        }
        if ($this->canUseDailyJob($dimensions)) {
            return $this->queryFromDailyJob($params);
        }
        // 没有合适的预聚合表，查明细表
        return $this->queryFromEvents($params);
    }

    private function queryFromDailyCompany($params)
    {
        $sql = "SELECT
                    event_date,
                    countMerge(pv) as pv,
                    uniqMerge(uv) as uv
                FROM stats.daily_company
                WHERE company_id = ? 
                  AND event_date BETWEEN ? AND ?
                  AND event_type = ?
                GROUP BY event_date
                ORDER BY event_date";
        
        return $this->clickhouse->query($sql, [
            $params['company_id'],
            $params['start_date'],
            $params['end_date'],
            $params['event_type'],
        ]);
    }
}
```

### 4.2 性能对比

| 查询场景 | MySQL 1.0 | ClickHouse 明细 | ClickHouse 预聚合 |
|---------|-----------|----------------|-----------------|
| 公司+天+事件类型 | 800ms | 150ms | 30ms |
| 公司+职位+天 | 3s | 300ms | 50ms |
| 公司+渠道+城市 | 12s | 800ms | -（无预聚合） |
| 趋势图（30天） | 5s | 200ms | 40ms |

平均查询性能提升 50 倍以上，用户体验从"转圈圈"变成"秒开"。

## 五、数据同步

### 5.1 Kafka 消费

ClickHouse 直接消费 Kafka：

```sql
CREATE TABLE stats.events_kafka (
    event_id String,
    event_type String,
    company_id Int32,
    job_id Int32,
    user_id Int32,
    channel String,
    city_id Int32,
    source String,
    created_at DateTime64(3)
) ENGINE = Kafka()
SETTINGS
    kafka_broker_list = 'kafka1:9092,kafka2:9092,kafka3:9092',
    kafka_topic_list = 'stats_events',
    kafka_group_name = 'clickhouse_stats',
    kafka_format = 'JSONEachRow',
    kafka_num_consumers = 3;

-- Materialized View 把 Kafka 数据写入明细表
CREATE MATERIALIZED VIEW stats.events_consumer TO stats.events AS
SELECT * FROM stats.events_kafka;
```

ClickHouse 原生支持 Kafka 引擎，不用自己写消费者，配置简单，性能高。

### 5.2 双写一致性

业务系统写 MySQL 和 Kafka 可能不一致（MySQL 成功但 Kafka 失败）。用事务消息（如 RocketMQ 的事务消息）保证最终一致，或者用 Canal 监听 MySQL binlog 同步到 Kafka，避免双写。

我们后来改成了 Canal 监听 binlog 的方案，业务系统只写 MySQL，Canal 自动同步到 Kafka，ClickHouse 消费 Kafka。这样业务系统无感知，数据一致性有保障。

## 六、踩过的坑

**1. Materialized View 不支持更新**

Materialized View 是插入时触发的，明细表的数据更新或删除不会同步到预聚合表。我们的场景是只追加不更新，所以没问题。如果有更新需求，要用 ReplacingMergeTree 或定期重算预聚合。

**2. uniq 精确去重内存开销大**

`uniqExact` 精确去重内存开销大，数据量大时容易 OOM。用 `uniq`（近似去重，误差 0.5%）替代，性能好很多，统计场景下近似值完全够用。

**3. 分区键选择**

分区键选了 `toYYYYMM(created_at)`，按月分区。查询时如果时间范围跨多个月，要扫描多个分区，性能稍差。但按月分区便于数据管理（过期数据直接 drop 分区），是合理的权衡。

**4. ORDER BY 设计**

ORDER BY 决定了数据的物理排序，对查询性能影响很大。我们按 `(company_id, event_type, created_at)` 排序，因为大部分查询都带 company_id 和 event_type 条件。如果查询条件不包含 ORDER BY 的前缀列，性能会下降。要根据实际查询模式设计 ORDER BY。

**5. 数据延迟**

Kafka + Materialized View 的方式有秒级延迟，不是实时的。对实时性要求高的场景（如实时大屏），要考虑用 Redis 做实时计数，ClickHouse 做历史分析。

## 七、总结

招聘通统计分析 2.0 升级的核心经验：

1. **OLAP 引擎选型**：ClickHouse 单机性能强，部署简单，适合中小团队的大数据分析场景
2. **列存+向量化**：列式存储 + 向量化执行，多维聚合查询比 MySQL 快几十倍
3. **Materialized View**：自动维护预聚合表，高频查询走预聚合，性能再提升一个量级
4. **分层查询**：查询服务自动路由到最优的表（预聚合或明细），兼顾性能和灵活性
5. **数据同步**：Canal 监听 binlog + Kafka + ClickHouse，业务系统无感知，数据一致性有保障
6. **注意坑点**：Materialized View 不支持更新、近似去重 vs 精确去重、分区键和 ORDER BY 设计、数据延迟

升级后，统计分析页面的查询从平均 5 秒降到 100 毫秒以内，用户体验大幅提升。而且架构上留了扩展空间，后续加新维度、新指标不用改核心架构，加个 Materialized View 就行。

OLAP 不是银弹，ClickHouse 适合大规模数据分析，但不适合事务处理（不支持事务，更新删除弱）。要根据业务场景选择，事务用 MySQL，分析用 ClickHouse，两者配合是最佳实践。
