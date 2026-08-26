---
title: "供应链频道页架构：迈点新闻与热门职位的聚合展示方案"
date: 2024-12-28T15:00:00+08:00
draft: false
tags: ["内容聚合", "架构设计", "PHP", "Go", "Redis", "缓存"]
categories: ["架构设计"]
summary: "供应链频道页的架构设计，聚合迈点新闻资讯、热门职位、行业数据等多源内容，通过缓存预聚合、异步更新、CDN 加速，实现高并发下频道页的快速响应。"
---

供应链频道页是酒店行业供应链的垂直频道，需要聚合展示迈点新闻资讯、热门职位、行业数据报告、供应链企业信息等多种来源的内容。页面内容多、更新频繁、访问量大，2024年12月做了专门的架构设计，今天分享出来。

## 一、内容来源

| 内容类型 | 来源 | 更新频率 | 数据量 |
|---------|------|---------|--------|
| 迈点新闻 | 迈点网 RSS/API | 每天更新 | 10万+ |
| 热门职位 | 招聘平台数据库 | 实时更新 | 5万+ |
| 行业报告 | 迈点研究院 | 每周更新 | 1000+ |
| 供应链企业 | 企业库 | 每月更新 | 5000+ |
| 行业数据 | 统计分析 | 每天更新 | 统计指标 |

## 二、架构设计

```
内容采集（RSS/API/DB）→ 内容清洗 → 内容存储（MySQL）→ 预聚合（Redis）→ 频道页 API → CDN 缓存 → 前端展示
```

### 内容采集

定时任务采集各来源内容：

```go
// 采集迈点新闻 RSS
func collectMeadinNews() error {
    feed, _ := rss.Parse("https://www.meadin.com/rss")
    for _, item := range feed.Items {
        // 清洗内容（去HTML标签、摘要提取、分类打标）
        cleaned := cleanNews(item)
        // 去重（按标题hash）
        if !isDuplicate(cleaned.TitleHash) {
            saveNews(cleaned)
        }
    }
    return nil
}
```

### 预聚合

频道页需要的内容提前聚合好存 Redis，不用每次请求查多个表：

```go
// 预聚合频道页数据
func preAggregateChannel() error {
    data := ChannelData{
        HotNews:    getHotNews(10),      // 热门新闻10条
        HotJobs:    getHotJobs(20),      // 热门职位20条
        Reports:    getLatestReports(5), // 最新报告5条
        Enterprises: getHotEnterprises(10), // 热门企业10家
        IndustryStats: getIndustryStats(), // 行业统计数据
    }

    // 存 Redis，1小时过期
    jsonData, _ := json.Marshal(data)
    redis.Set("channel:supply_chain", jsonData, time.Hour)
    return nil
}
```

定时任务每小时预聚合一次，或者内容更新时触发预聚合。

### 频道页 API

API 直接读 Redis 缓存，响应时间 < 10ms：

```go
func (h *ChannelHandler) SupplyChain(c *gin.Context) {
    // 读 Redis 缓存
    data := redis.Get("channel:supply_chain").Val()
    if data != "" {
        var channelData ChannelData
        json.Unmarshal([]byte(data), &channelData)
        c.JSON(200, gin.H{"code": 0, "data": channelData})
        return
    }

    // 缓存未命中，实时查询（降级）
    channelData := queryChannelData()
    c.JSON(200, gin.H{"code": 0, "data": channelData})
}
```

### CDN 加速

频道页是静态内容为主，用 CDN 缓存整个页面：

```nginx
# 频道页 CDN 缓存 10 分钟
location /channel/supply-chain {
    proxy_pass http://backend;
    proxy_cache_valid 200 10m;
    add_header X-Cache-Status $upstream_cache_status;
}
```

## 三、内容去重

不同来源可能有相同内容，用标题 + 内容 hash 去重：

```go
func isDuplicate(title, content string) bool {
    titleHash := md5.Sum([]byte(title))
    contentHash := md5.Sum([]byte(content[:200])) // 前200字hash
    key := fmt.Sprintf("news:dup:%x:%x", titleHash, contentHash)
    return redis.SetNX(key, "1", 30*24*time.Hour).Val() == false
}
```

## 四、踩坑经验

1. **RSS 源不稳定**：迈点 RSS 偶尔超时或格式变化。加重试机制和格式容错，解析失败记日志不中断
2. **内容分类不准**：自动分类新闻到行业（酒店/餐饮/供应链）准确率不高。加了关键词规则 + 人工审核，热门内容人工确认分类
3. **缓存击穿**：Redis 缓存过期瞬间，大量请求打到数据库。加互斥锁（SETNX），只有一个请求查数据库，其他等待缓存
4. **职位数据实时性**：热门职位要求实时更新，但预聚合是每小时一次。职位部分单独做实时查询（带缓存），其他内容用预聚合，兼顾实时性和性能

## 五、总结

供应链频道页架构核心：

1. **内容聚合**：多来源内容统一采集、清洗、存储，消除数据源差异
2. **预聚合**：频道页需要的内容提前聚合好存 Redis，不用每次查多表
3. **多级缓存**：Redis 预聚合 + CDN 页面缓存 + 本地缓存，层层拦截
4. **异步更新**：内容采集、清洗、预聚合都异步处理，不影响用户访问
5. **内容去重**：标题+内容 hash 去重，避免重复内容
6. **降级方案**：缓存未命中时实时查询降级，保证可用性

内容聚合类页面的特点是"读多写少、内容来源多、更新不要求绝对实时"，适合用预聚合 + 多级缓存的方案。把复杂的聚合逻辑放在异步任务里，用户请求只读缓存，性能和稳定性都有保障。
