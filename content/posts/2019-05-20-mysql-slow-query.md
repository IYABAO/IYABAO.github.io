---
title: "MySQL 慢查询深度分析：从 EXPLAIN 到索引优化的完整排查链路"
date: 2019-05-20T14:20:00+08:00
draft: false
tags: ["MySQL", "性能优化", "EXPLAIN", "索引"]
categories: ["数据库"]
summary: "线上 MySQL 慢查询排查的完整方法论，从慢查询日志定位到 EXPLAIN 执行计划分析，再到索引优化和 SQL 改写的实战记录。"
---

做后端开发，跟 MySQL 慢查询打交道是家常便饭。今天把我这几年排查慢查询的完整链路整理出来，从发现问题到定位根因再到优化落地，一步一步讲清楚。

## 一、发现问题：慢查询日志

排查慢查询的第一步是开启慢查询日志，把执行时间超过阈值的 SQL 记录下来。

```sql
-- 查看慢查询配置
SHOW VARIABLES LIKE 'slow_query%';
SHOW VARIABLES LIKE 'long_query_time';

-- 临时开启（重启失效）
SET GLOBAL slow_query_log = 'ON';
SET GLOBAL long_query_time = 1; -- 超过1秒记录
```

生产环境建议 `long_query_time` 设为 1 秒，太低了日志量会很大。日志文件路径看 `slow_query_log_file`。

拿到慢查询日志后，用 `mysqldumpslow` 工具做聚合分析：

```bash
# 按查询次数排序，取前20
mysqldumpslow -s c -t 20 /var/log/mysql/slow.log

# 按总耗时排序
mysqldumpslow -s t -t 20 /var/log/mysql/slow.log
```

这个工具会把 SQL 里的常量替换成 `N` 或 `S`，做聚合统计，能快速定位哪些 SQL 慢得最频繁。

## 二、定位根因：EXPLAIN 执行计划

找到慢 SQL 后，用 `EXPLAIN` 看执行计划。这是排查慢查询最核心的工具。

```sql
EXPLAIN SELECT * FROM resume WHERE user_id = 123 AND status = 1 ORDER BY created_at DESC LIMIT 20;
```

EXPLAIN 输出的字段很多，我重点看这几个：

### 2.1 type：访问类型

`type` 字段表示 MySQL 找到行的方式，性能从好到差：

```
system > const > eq_ref > ref > range > index > ALL
```

- `const`：主键或唯一索引等值查询，最快
- `eq_ref`：联表时用主键或唯一索引关联
- `ref`：非唯一索引等值查询
- `range`：索引范围查询（BETWEEN, IN, >, <）
- `index`：全索引扫描，比全表扫描好一点但还是慢
- `ALL`：全表扫描，必须优化

如果看到 `type = ALL`，基本就是没走索引，需要加索引或者改写 SQL。

### 2.2 key：实际使用的索引

`key` 字段显示 MySQL 实际选择的索引。如果 `key` 是 NULL，说明没走索引。

`possible_keys` 显示可能用到的索引。如果 `possible_keys` 有值但 `key` 是 NULL，可能是索引选择性太差，MySQL 觉得全表扫描更快。

### 2.3 rows：预估扫描行数

`rows` 字段表示 MySQL 预估需要扫描的行数。这个值越大越慢。如果实际只返回几行但 rows 是几万，说明索引没建好。

### 2.4 Extra：额外信息

`Extra` 字段有几个关键值需要警惕：

- `Using filesort`：需要额外排序，数据量大时很慢
- `Using temporary`：使用临时表，常见于 GROUP BY 或 DISTINCT
- `Using where`：在存储引擎层过滤后还需要在 Server 层过滤
- `Using index condition`：索引下推，5.6+ 的优化，是好事

## 三、实战案例

说个真实案例。招聘系统里有个简历查询接口，线上偶尔超时，慢查询日志里抓到这条 SQL：

```sql
SELECT id, title, user_id, created_at 
FROM resume 
WHERE status = 1 
  AND city_id IN (1, 2, 3, 5, 8, 13, 21, 34, 55, 89)
  AND experience >= 3
ORDER BY created_at DESC 
LIMIT 20;
```

EXPLAIN 结果：

```
id: 1
select_type: SIMPLE
table: resume
type: ALL
possible_keys: idx_status_city, idx_created_at
key: NULL
rows: 285634
Extra: Using where; Using filesort
```

全表扫描 28 万行，还有 filesort，不慢才怪。

### 3.1 分析问题

`possible_keys` 里有两个索引：
- `idx_status_city (status, city_id)`
- `idx_created_at (created_at)`

但 MySQL 一个都没选。原因是：
- `idx_status_city` 的选择性不好，status=1 占了 70% 的数据，city_id IN 条件也覆盖了大部分城市
- `idx_created_at` 可以避免 filesort，但需要扫描大量行后再用 WHERE 过滤

MySQL 优化器算下来觉得全表扫描更快，实际上全表扫描 28 万行加 filesort 要 3 秒多。

### 3.2 优化方案

建一个联合索引，把过滤条件和排序都覆盖到：

```sql
ALTER TABLE resume ADD INDEX idx_status_city_created (status, city_id, created_at);
```

注意联合索引的列顺序：等值查询的列在前，范围查询的列在中间，排序列在后。

再 EXPLAIN：

```
type: range
key: idx_status_city_created
rows: 12450
Extra: Using where; Using index condition
```

走了索引，扫描行数从 28 万降到 1.2 万，filesort 也没了（索引本身就是按 created_at 排序的）。执行时间从 3.2 秒降到 80 毫秒。

### 3.3 进一步优化：覆盖索引

如果查询的列不多，可以建覆盖索引，避免回表：

```sql
ALTER TABLE resume ADD INDEX idx_cover (status, city_id, created_at, id, title, user_id);
```

EXPLAIN 的 Extra 会出现 `Using index`，表示直接从索引返回数据，不需要回表查询。性能还能再提升 30% 左右。

但覆盖索引不是越多越好，索引列太多会增加写入开销和存储空间。要根据实际查询频率权衡。

## 四、常见优化手段

### 4.1 避免 SELECT *

`SELECT *` 会导致：
1. 无法使用覆盖索引，必须回表
2. 传输不必要的列，增加网络开销
3. 表结构变更时可能引发兼容性问题

只查需要的列，是最基本也是最有效的优化。

### 4.2 LIMIT 深分页优化

```sql
-- 慢：深分页时需要扫描前面所有行
SELECT * FROM resume ORDER BY created_at DESC LIMIT 100000, 20;

-- 快：用子查询定位ID，再回表
SELECT r.* FROM resume r
INNER JOIN (
    SELECT id FROM resume ORDER BY created_at DESC LIMIT 100000, 20
) t ON r.id = t.id;
```

原理是子查询可以用覆盖索引快速定位 ID，再用 ID 回表，避免扫描大量行后丢弃。

### 4.3 JOIN 优化

- 小表驱动大表，MySQL 优化器会自动选择，但有时候需要用 `STRAIGHT_JOIN` 强制
- JOIN 的关联字段必须建索引
- 避免 JOIN 太多表，一般不超过 3 张，超过的话考虑冗余字段或应用层组装

### 4.4 GROUP BY 优化

GROUP BY 默认会排序，如果不需要排序可以加 `ORDER BY NULL`：

```sql
SELECT city_id, COUNT(*) FROM resume GROUP BY city_id ORDER BY NULL;
```

这样可以避免 `Using temporary; Using filesort`。

## 五、索引设计原则

1. **最左前缀原则**：联合索引按列顺序匹配，跳过的列后面的索引用不上
2. **等值在前，范围在后**：等值查询的列放前面，范围查询的列放后面
3. **高选择性列优先**：区分度高的列（如 user_id）放前面，区分度低的（如 status）放后面
4. **排序列并入索引**：经常 ORDER BY 的列可以放进联合索引，避免 filesort
5. **索引不是越多越好**：每个索引都增加写入开销，一般单表索引不超过 5 个
6. **定期清理无用索引**：用 `sys.schema_unused_indexes` 查看从未使用的索引

## 六、总结

MySQL 慢查询排查的完整链路：

1. **慢查询日志**发现问题 SQL
2. **EXPLAIN** 分析执行计划，看 type、key、rows、Extra
3. **定位根因**：没走索引？索引选择性差？filesort？深分页？
4. **优化手段**：加联合索引、改写 SQL、覆盖索引、应用层处理
5. **验证效果**：再次 EXPLAIN + 实际执行时间对比

这套方法我用了很多年，90% 以上的慢查询都能通过这个链路解决。剩下的 10% 是业务逻辑本身的问题，需要从架构层面重构，不是加索引能解决的。

数据库优化是个持续的过程，业务在变，数据量在涨，今天最优的索引明天可能就不行了。定期 review 慢查询日志，是每个后端开发者的必修课。
