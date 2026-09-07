---
title: "SQL 优化实战：从慢查询到索引设计"
date: 2023-09-19T09:00:00+08:00
lastmod: 2023-09-19T09:00:00+08:00
draft: false
author: IYABAO
tags:
  - MySQL
  - SQL优化
  - 索引
categories:
  - 技术
summary: "一条 SQL 从 3 秒到 5 毫秒的完整过程：慢查询定位、执行计划解读、索引设计原则、常见反模式——SQL 优化的实战手册。"
---

# SQL 优化实战：从慢查询到索引设计

线上"接口突然变慢"的头号原因：**慢 SQL**。一条 3 秒的查询在高峰能把连接池打满，拖垮整个服务。这篇文章是 SQL 优化的完整实战：定位 → 分析 → 优化 → 验证。

## 一、定位慢查询

```sql
-- 1. 开启慢查询日志
SET GLOBAL slow_query_log = ON;
SET GLOBAL long_query_time = 1;      -- 超过 1 秒记录

-- 2. 查看最近慢查询
SHOW GLOBAL STATUS LIKE 'Slow_queries';
-- 慢查询日志里看到：SQL 文本 + 执行时间 + 扫描行数

-- 3. 生产常用：performance_schema
SELECT * FROM performance_schema.events_statements_summary_by_digest
ORDER BY SUM_TIMER_WAIT DESC LIMIT 10;   -- Top 慢 SQL 排行
```

## 二、执行计划解读

```sql
EXPLAIN SELECT * FROM orders 
WHERE user_id = 123 AND status = 'PAID' 
ORDER BY created_at DESC LIMIT 10;
```

```
关键字段：
  type：访问类型（const > ref > range > index > ALL）
    ALL = 全表扫描（重点优化对象）
  key：用到的索引（NULL = 没用索引！）
  rows：扫描行数（越小越好）
  Extra：
    Using filesort = 排序没走索引（要优化）
    Using temporary = 用了临时表（要优化）
    Using index = 覆盖索引（最优）
```

## 三、索引设计原则

### 1. 最左前缀

```sql
-- 联合索引 (user_id, status, created_at)
-- 能用：user_id；user_id+status；user_id+status+created_at
-- 不能用：status（跳过了最左列）！status+created_at 也不行
```

### 2. 覆盖索引

```sql
-- 查询的字段都在索引里 → 不用回表
CREATE INDEX idx_user_status ON orders(user_id, status, amount);
SELECT user_id, status, amount FROM orders WHERE user_id = 123;
-- Extra: Using index（全从索引拿，不回表）→ 快很多
```

### 3. 索引下推（ICP）

```sql
-- MySQL 5.6+：联合索引里，对二级字段的过滤在索引层做
CREATE INDEX idx_user_status ON orders(user_id, status);
SELECT * FROM orders WHERE user_id = 123 AND status = 'PAID';
-- status 的过滤在索引层完成（减少回表次数）
```

## 四、常见反模式与修复

### 反模式 1：函数导致索引失效

```sql
-- ❌ 对索引列用函数 → 索引失效
WHERE DATE(created_at) = '2026-09-07'
-- ✅ 改为范围查询（索引可用）
WHERE created_at >= '2026-09-07 00:00:00' 
  AND created_at < '2026-09-08 00:00:00'
```

### 反模式 2：隐式类型转换

```sql
-- ❌ user_id 是 varchar 索引列，却传数字
WHERE user_id = 12345678901   -- 数字 → 隐式转 → 索引失效
-- ✅ 传字符串
WHERE user_id = '12345678901'
```

### 反模式 3：前缀模糊

```sql
-- ❌ % 开头的模糊 → 索引失效
WHERE name LIKE '%李%'
-- ✅ 后缀模糊可用索引
WHERE name LIKE '李%'
-- 真需要全文模糊 → 用 ES / 全文索引
```

### 反模式 4：OR 连接

```sql
-- ❌ OR 两边字段不同索引 → 可能全表扫
WHERE user_id = 1 OR status = 'PAID'
-- ✅ 拆 UNION 或确认两边都有索引
```

### 反模式 5：SELECT *

```sql
-- ❌ SELECT * → 回表 + 传大字段
-- ✅ 只查需要的字段（可能命中覆盖索引）
```

## 五、分页优化（深分页）

```sql
-- ❌ 深分页：LIMIT 100000, 20 → 扫 10 万行丢弃
SELECT * FROM orders ORDER BY id LIMIT 100000, 20;
-- ✅ 游标分页（用 id 条件代替 offset）
SELECT * FROM orders WHERE id > 100000 ORDER BY id LIMIT 20;
```

## 六、一个完整案例

```
慢 SQL：查询 3.2 秒
SELECT * FROM resume 
WHERE city='杭州' AND expect_position LIKE '%后端%' 
ORDER BY update_time DESC LIMIT 20;
-- 扫描 120 万行（全表），Using filesort

优化：
  1. 加索引：idx_city_update (city, update_time)  -- 等值+排序
  2. LIKE 前缀模糊问题：expect_position 精确匹配场景走 ES（复杂检索）
  3. 只查必要字段（减少回表）

结果：3.2 秒 → 8 毫秒（-99.7%），扫描行数 120 万 → 2 万
```

## 七、踩坑记录

1. **加索引不验证**：加了索引但查询没走（函数/类型转换）→ 用 EXPLAIN 确认 key 用上了
2. **冗余索引**：idx_a、idx_ab、idx_abc 三个索引 → 写放大 + 占用 → 只留 (a,b,c) 和必要单列
3. **只优化单条 SQL 不看整体**：一个查询快了，其他查询被挤掉缓存 → 压测验证整体吞吐
4. **忽略写放大**：核心表加 5 个索引 → 写入慢 3 倍 → 索引要覆盖"读写平衡"

## 总结

SQL 优化的核心认知：

1. **定位靠慢查询日志**（Top SQL 排行）
2. **解读靠 EXPLAIN**（type/key/rows/Extra 四个关键）
3. **索引三原则**：最左前缀、覆盖索引、索引下推
4. **反模式五类**：函数、隐式转换、前缀模糊、OR、SELECT *
5. **验证闭环**：EXPLAIN + 压测，别只"觉得快了"

**SQL 优化 80% 是索引问题，20% 是写法问题。** 会看 EXPLAIN、懂索引原理，慢 SQL 基本都能压到毫秒级——这是后端的基本功，也是排查线上问题的第一手武器。
