---
title: "薪酬报告大数据统计系统架构设计：亿级数据下的预聚合方案"
date: 2019-07-08T09:45:00+08:00
draft: false
tags: ["大数据", "架构设计", "预聚合", "Elasticsearch", "MySQL"]
categories: ["架构设计"]
summary: "招聘平台薪酬报告系统从 MySQL 实时统计到 Elasticsearch 预聚合的架构演进，解决亿级数据下多维组合查询响应慢的问题。"
---

招聘平台有个薪酬报告功能，用户可以按行业、城市、职位、工作经验等维度组合查询薪资分布。数据量到了亿级之后，MySQL 实时统计根本扛不住，一次查询要十几秒。后来重构了一版，用预聚合方案把响应时间压到了 200 毫秒以内。今天把整个架构设计过程分享出来。

## 一、背景与问题

薪酬报告的数据来源是企业发布的职位薪资，每天新增几十万条，累计到了 1.2 亿条。查询维度包括：

- 行业（20+）
- 城市（300+）
- 职位类别（500+）
- 工作经验（0-3年, 3-5年, 5-10年, 10年+）
- 学历（大专, 本科, 硕士, 博士）
- 公司规模（10个档位）

用户可以任意组合这些维度，查询薪资的中位数、平均值、25分位、75分位等统计指标。

### 1.1 原始方案

最开始直接用 MySQL 实时统计：

```sql
SELECT 
    AVG(salary_min) as avg_min,
    AVG(salary_max) as avg_max,
    COUNT(*) as cnt
FROM job_salary
WHERE industry = 15
  AND city = 2
  AND job_category = 128
  AND experience = '3-5年'
  AND education = '本科';
```

单维度查询还能接受，3-5 个维度组合后，WHERE 条件过滤后还要扫描几十万行，响应时间 5-15 秒。用户体验极差，经常超时。

### 1.2 问题分析

核心矛盾是：**多维组合查询的维度笛卡尔积太大，无法为每种组合都建索引**。

5 个维度，每个维度的取值数相乘，理论上有 20×300×500×4×4 = 4800 万种组合。虽然实际有数据的组合没那么多，但也远远超出了 MySQL 索引能覆盖的范围。

## 二、预聚合方案

思路很简单：**把常用维度组合的统计结果提前算好，存起来，查询时直接读结果**。

这就是 OLAP（联机分析处理）的核心思想，用空间换时间。

### 2.1 维度组合设计

不是所有维度组合都需要预聚合。我们分析了线上查询日志，发现 95% 的查询集中在以下几种组合：

1. 行业 + 城市 + 职位 + 经验
2. 行业 + 城市 + 职位 + 学历
3. 行业 + 城市 + 经验 + 学历
4. 行业 + 职位 + 经验 + 学历
5. 城市 + 职位 + 经验 + 学历
6. 行业 + 城市 + 职位
7. 行业 + 城市 + 经验
8. 行业 + 职位 + 经验

按这些组合预聚合，覆盖了绝大部分查询。剩下的 5% 走实时查询，或者提示用户缩小查询范围。

### 2.2 预聚合表设计

每种维度组合对应一张预聚合表：

```sql
CREATE TABLE `salary_agg_industry_city_job_exp` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `industry` int(11) NOT NULL,
  `city` int(11) NOT NULL,
  `job_category` int(11) NOT NULL,
  `experience` varchar(20) NOT NULL,
  `count` int(11) NOT NULL DEFAULT '0' COMMENT '样本数',
  `avg_min` decimal(10,2) NOT NULL DEFAULT '0.00' COMMENT '平均最低薪',
  `avg_max` decimal(10,2) NOT NULL DEFAULT '0.00' COMMENT '平均最高薪',
  `median` decimal(10,2) NOT NULL DEFAULT '0.00' COMMENT '中位数',
  `p25` decimal(10,2) NOT NULL DEFAULT '0.00' COMMENT '25分位',
  `p75` decimal(10,2) NOT NULL DEFAULT '0.00' COMMENT '75分位',
  `updated_at` int(11) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `dim` (`industry`,`city`,`job_category`,`experience`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

关键点：
- 维度列加联合唯一索引，查询时直接走主键或唯一索引，极快
- 统计指标列全部预计算好，查询时不需要任何计算
- `count` 字段记录样本数，样本太少的组合可以过滤掉，避免统计偏差

### 2.3 分位数计算

平均值、计数这些好算，增量更新也容易。但分位数（中位数、25分位、75分位）的增量计算比较麻烦。

我们的方案是：预聚合时不做增量更新，而是每天凌晨全量重算。1.2 亿条数据，用 Spark 跑批，每天重算所有预聚合表，耗时约 20 分钟。薪酬数据对实时性要求不高，T+1 更新完全够用。

Spark 计算分位数用 `approxQuantile` 方法：

```scala
val df = spark.read.jdbc(url, "job_salary", props)

val result = df
  .filter("status = 1 AND salary_min > 0")
  .groupBy("industry", "city", "job_category", "experience")
  .agg(
    count("*").as("count"),
    avg("salary_min").as("avg_min"),
    avg("salary_max").as("avg_max"),
    expr("percentile_approx(salary_min, 0.5)").as("median"),
    expr("percentile_approx(salary_min, 0.25)").as("p25"),
    expr("percentile_approx(salary_min, 0.75)").as("p75")
  )

result.write.mode("overwrite").jdbc(url, "salary_agg_industry_city_job_exp", props)
```

`percentile_approx` 是近似分位数算法，精度可控，比精确计算快很多。薪酬报告场景下，近似值完全够用。

## 三、查询层设计

预聚合表建好后，查询层要根据用户选择的维度，自动路由到对应的预聚合表。

### 3.1 路由逻辑

```php
public function querySalaryReport($filters)
{
    // 根据筛选维度选择预聚合表
    $dimensions = $this->getActiveDimensions($filters);
    $aggTable = $this->routeToAggTable($dimensions);

    if ($aggTable) {
        // 走预聚合表
        return $this->queryFromAggTable($aggTable, $filters);
    } else {
        // 未覆盖的维度组合，走实时查询或降级
        return $this->queryRealtime($filters);
    }
}

private function routeToAggTable($dimensions)
{
    $map = [
        'industry,city,job_category,experience' => 'salary_agg_industry_city_job_exp',
        'industry,city,job_category,education' => 'salary_agg_industry_city_job_edu',
        'industry,city,experience,education' => 'salary_agg_industry_city_exp_edu',
        'industry,job_category,experience,education' => 'salary_agg_industry_job_exp_edu',
        'city,job_category,experience,education' => 'salary_agg_city_job_exp_edu',
        'industry,city,job_category' => 'salary_agg_industry_city_job',
        'industry,city,experience' => 'salary_agg_industry_city_exp',
        'industry,job_category,experience' => 'salary_agg_industry_job_exp',
    ];

    $key = implode(',', $dimensions);
    return $map[$key] ?? null;
}
```

### 3.2 上卷聚合

如果用户选的维度比预聚合表少，比如只选了行业+城市，而预聚合表是行业+城市+职位+经验，可以在预聚合表的基础上做上卷（roll-up）聚合：

```sql
SELECT 
    industry, city,
    SUM(count) as total_count,
    AVG(avg_min) as avg_min,
    AVG(avg_max) as avg_max
FROM salary_agg_industry_city_job_exp
WHERE industry = 15 AND city = 2
GROUP BY industry, city;
```

这样预聚合表的粒度越细，能覆盖的查询场景越多。我们最细的粒度是 4 个维度，更粗的查询都可以通过上卷实现。

## 四、后来的演进：Elasticsearch

MySQL 预聚合方案跑了一年多，后来业务方要求支持更多维度组合（加了公司规模、融资阶段等），预聚合表的数量爆炸式增长，维护成本很高。

第二版改用 Elasticsearch，用它的聚合查询能力替代预聚合表：

```json
{
  "query": {
    "bool": {
      "filter": [
        {"term": {"industry": 15}},
        {"term": {"city": 2}},
        {"term": {"job_category": 128}},
        {"term": {"experience": "3-5年"}}
      ]
    }
  },
  "aggs": {
    "salary_stats": {
      "stats": {"field": "salary_min"}
    },
    "salary_percentiles": {
      "percentiles": {
        "field": "salary_min",
        "percents": [25, 50, 75]
      }
    }
  }
}
```

Elasticsearch 的优势：
- 不需要预聚合，任意维度组合都能实时查询
- 内置分位数、直方图等聚合函数
- 水平扩展能力强，数据量再大也能扛

但也有代价：
- 硬件成本高，ES 集群比 MySQL 贵
- 数据同步有延迟，需要维护 MySQL 到 ES 的同步链路
- 精确性不如 MySQL，分位数是近似算法

我们最终的方案是：高频查询走 ES，对精确性要求高的报表走 MySQL 预聚合。两者互补。

## 五、总结

薪酬报告系统的架构演进经历了三个阶段：

1. **MySQL 实时统计**：数据量小的时候够用，亿级后响应慢到不可用
2. **MySQL 预聚合**：用空间换时间，把常用维度组合提前算好，响应时间从十几秒降到 200 毫秒以内
3. **Elasticsearch 聚合查询**：支持任意维度组合，灵活性更高，但成本和复杂度也更高

核心经验：
- 预聚合是解决多维统计查询的经典方案，适用场景是维度相对固定、对实时性要求不高
- 预聚合表的粒度设计很关键，最细粒度决定了能覆盖多少查询场景
- 分位数计算用近似算法（如 T-Digest），性能和精度的平衡要根据业务需求调整
- 没有银弹，MySQL 预聚合和 ES 各有优劣，根据场景选择或组合使用

这个系统现在还在跑，每天支撑几万次薪酬查询，稳定性和性能都没问题。架构设计没有最好的，只有最合适的。在当时的业务规模和团队能力下，预聚合方案是性价比最高的选择。
