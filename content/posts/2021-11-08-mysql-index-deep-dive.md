---
title: "MySQL 索引深度：为什么你的 SQL 还是慢"
date: 2021-11-08T09:00:00+08:00
lastmod: 2021-11-08T09:00:00+08:00
draft: false
author: IYABAO
tags:
  - MySQL
  - 索引
  - 性能优化
categories:
  - 技术
summary: "索引不是'建了就快'。B+树高度、最左前缀、回表、覆盖索引、索引下推，从原理到 EXPLAIN 实战，把慢 SQL 优化的完整套路讲清楚。"
---

# MySQL 索引深度：为什么你的 SQL 还是慢

"我建了索引，为什么还是慢？"——这是被问得最多的性能问题。索引不是"建了就快"，用错了反而更慢。这篇从 B+ 树原理讲到 EXPLAIN 实战，把索引优化的完整套路讲清楚。

## 一、先理解 B+ 树：索引为什么快

MySQL InnoDB 的索引是 B+ 树：

- 叶子节点存数据（聚簇索引）或主键（二级索引）
- 树高 3-4 层，一次查询 3-4 次磁盘 IO
- 千万级数据树高也就 4 层——**这就是索引快的根本**

**两个核心概念**：

1. **聚簇索引**：主键索引，叶子节点存整行数据
2. **二级索引**：非主键索引，叶子节点存主键值——查询需要**回表**（先查二级索引拿主键，再查聚簇索引拿数据）

## 二、最左前缀：联合索引的第一法则

```sql
-- 建联合索引
ALTER TABLE resume ADD INDEX idx_city_age (city, age);
```

这个索引能命中：

```sql
WHERE city='杭州'           ✅
WHERE city='杭州' AND age>25 ✅
WHERE age>25                ❌ 跳过最左列，索引失效
```

**原理**：联合索引的 B+ 树先按第一列排，再按第二列排。"跳过第一列"等于在整棵树上乱序查找。

### 实践经验

- 联合索引**把等值条件放前面，范围条件放后面**：`(city, age)` 比 `(age, city)` 更能利用索引
- **区分度高的列放前面**：`(gender, city)` 里 gender 只有 2 个值，区分度差，浪费索引空间
- 索引不是越多越好：每个索引都是写开销，**最左前缀能复用的就一个**（`(a,b,c)` 可以覆盖 `(a)`、`(a,b)`、`(a,b,c)` 三种查询）

## 三、回表与覆盖索引

```sql
-- 二级索引 idx_city_age，查询 city 和 age
SELECT city, age FROM resume WHERE city='杭州';  -- 索引里就有，不用回表 ✅
SELECT * FROM resume WHERE city='杭州';           -- 要拿整行 → 回表 ❌
```

**覆盖索引**：查询的列都在索引里，就不用回表，快一个数量级。

```sql
-- 经典优化：把高频查询的列加到索引尾部，做成覆盖索引
-- 查询 SELECT name, city FROM resume WHERE city='杭州'
ALTER TABLE resume ADD INDEX idx_city_name (city, name);
-- 此时 name、city 都在索引里 → 覆盖索引，零回表
```

## 四、索引失效的 8 个经典场景

```sql
1. LIKE '%xx'          -- 前置模糊，索引失效（'xx%' 可以用）
2. 函数/运算包裹列     -- WHERE YEAR(create_time)=2021 → 改成范围查询
3. 隐式类型转换        -- WHERE phone=13800000000（phone 是 varchar）
4. OR 连接非索引列     -- city='杭州' OR name='张三'（name 无索引）
5. != / NOT IN         -- 一般不走索引（数据量小可接受）
6. 字符集不一致        -- JOIN 两表字段 collation 不同
7. 排序不遵循最左前缀  -- ORDER BY age（索引是 city,age）
8. 数据量太小          -- 全表扫比索引快，优化器不选索引
```

**经验**：遇到慢 SQL，先 `EXPLAIN` 看 `type` 字段——`const/ref/range` 是走索引，`ALL` 是全表扫，`index` 是扫全索引。

## 五、实战：一个慢 SQL 的优化全程

**问题**：简历列表页 `SELECT * FROM resume WHERE city='杭州' ORDER BY update_time DESC LIMIT 20`，300ms。

**EXPLAIN**：type=ALL，全表扫。

**优化**：

```sql
-- 1. 先加联合索引
ALTER TABLE resume ADD INDEX idx_city_update (city, update_time);
-- 2. 结果：type=ref，range 内排序走索引，20ms
```

**为什么快**：索引 `(city, update_time)` 让"城市筛选 + 时间排序"一次完成——排序不再需要 filesort（临时文件排序）。

## 六、深分页的终极解法

```sql
-- 深分页慢：LIMIT 100000, 20 要先扫 10 万行再丢弃
SELECT * FROM resume ORDER BY id LIMIT 100000, 20;  -- 1.2s

-- 优化：延迟关联（先查索引里的主键，再回表）
SELECT r.* FROM resume r
JOIN (SELECT id FROM resume ORDER BY id LIMIT 100000, 20) tmp
ON r.id = tmp.id;  -- 120ms

-- 或：记录上一页最后 ID（业务允许时最佳）
SELECT * FROM resume WHERE id > 100020 ORDER BY id LIMIT 20;  -- 5ms
```

## 七、索引设计检查清单

```
✅ 高频查询的 WHERE 条件建索引
✅ 联合索引：等值在前、范围在后、区分度高的在前
✅ 覆盖索引：SELECT 的列尽量都在索引里
✅ 排序字段进索引（避免 filesort）
✅ 每表索引 ≤ 5 个（写多读少的表更少）
✅ 大字段（TEXT）不建索引
✅ 定期用 pt-query-digest / 慢日志分析新慢 SQL
```

## 总结

索引优化的完整认知链：

1. **原理**：B+ 树 3-4 层，二级索引要回表
2. **组合**：最左前缀决定联合索引怎么建
3. **失效**：函数/隐式转换/前置模糊，EXPLAIN 看 type
4. **优化**：覆盖索引 + 延迟关联 + 游标分页

**慢 SQL 不是玄学，是没按 B+ 树的脾气来。** 建索引前先想三个问题：等值还是范围？要不要回表？能不能覆盖？
