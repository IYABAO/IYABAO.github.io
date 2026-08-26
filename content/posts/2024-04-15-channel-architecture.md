---
title: "138 大美业模块架构设计：多行业垂直频道的可扩展方案"
date: 2024-04-15T14:00:00+08:00
draft: false
tags: ["架构设计", "垂直频道", "可扩展", "PHP", "Go", "多租户"]
categories: ["架构设计"]
summary: "138 大美业垂直频道模块的架构设计，支持多行业垂直频道的快速扩展，涵盖频道配置化、数据隔离、主题定制、统一接口，实现新增频道零代码开发。"
---

138 大美业是我们平台的美业垂直招聘频道，后续还要扩展到酒店、餐饮、零售等多个垂直行业。如果每个频道都单独开发一套，维护成本太高。2024年4月做了可扩展的垂直频道架构，新增频道只需要配置，不用写代码。

## 一、核心设计

### 频道配置化

每个频道的信息、字段、主题、功能都存在配置表里：

```sql
CREATE TABLE `channel` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `code` varchar(50) NOT NULL COMMENT '频道编码：meiye/hotel/canyin',
  `name` varchar(50) NOT NULL COMMENT '频道名称',
  `domain` varchar(100) NOT NULL COMMENT '频道域名',
  `config` text COMMENT '频道配置（JSON）：主题色、字段、功能开关',
  `status` tinyint(1) NOT NULL DEFAULT '1',
  PRIMARY KEY (`id`),
  UNIQUE KEY `code` (`code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

配置示例：
```json
{
  "theme": {"primary_color": "#ff6b6b", "logo": "meiye.png"},
  "job_fields": ["salary", "experience", "education", "beauty_skill"],
  "resume_fields": ["avatar", "basic_info", "work_experience", "certificate"],
  "features": {"video_resume": true, "online_interview": false, "live_recruitment": true}
}
```

### 数据隔离

所有业务表带 `channel_code` 字段，频道间数据隔离：

```sql
CREATE TABLE `channel_job` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `channel_code` varchar(50) NOT NULL,
  `company_id` bigint(20) NOT NULL,
  `title` varchar(100) NOT NULL,
  `salary_min` int(11) NOT NULL,
  `salary_max` int(11) NOT NULL,
  `extra_fields` text COMMENT '扩展字段（JSON），不同频道字段不同',
  `status` tinyint(1) NOT NULL DEFAULT '1',
  `created_at` int(11) NOT NULL,
  PRIMARY KEY (`id`),
  KEY `channel_status_created` (`channel_code`,`status`,`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

不同频道的特有字段存在 `extra_fields` JSON 字段里，不用加列。

### 统一接口

所有频道共用一套 API，通过 `channel_code` 区分：

```go
func (h *JobHandler) List(c *gin.Context) {
    channelCode := c.GetHeader("X-Channel-Code") // 从 header 取频道
    channel := h.channelService.GetByCode(channelCode)
    
    // 根据频道配置查询
    query := h.jobRepo.Query().Where("channel_code = ?", channelCode)
    if c.Query("keyword") != "" {
        query = query.Where("title LIKE ?", "%"+c.Query("keyword")+"%")
    }
    
    jobs := query.Order("created_at DESC").Limit(20).Find()
    c.JSON(200, gin.H{"code": 0, "data": jobs})
}
```

前端根据频道配置动态渲染页面，不同频道显示不同的字段和主题。

## 二、扩展新频道流程

新增一个酒店频道，只需要：

1. 在 `channel` 表插入一条配置记录
2. 配置主题色、字段、功能开关
3. 绑定域名
4. 上线，零代码开发

## 三、踩坑经验

1. **JSON 字段查询慢**：`extra_fields` 里的字段查询用 JSON_EXTRACT，性能差。常用的扩展字段单独建列，不常用的放 JSON
2. **频道配置缓存**：每次请求都查频道配置，数据库压力大。用 Redis 缓存，配置变更时主动清缓存
3. **频道间数据串了**：早期接口没强制校验 channel_code，用户能看到其他频道的数据。加了中间件统一校验，所有请求必须带有效的 channel_code

## 四、总结

垂直频道可扩展架构核心：

1. **配置化**：频道信息、字段、主题、功能都配置化，新增频道零代码
2. **数据隔离**：所有表带 channel_code，频道间数据隔离
3. **扩展字段**：不同频道的特有字段用 JSON 存储，不用频繁加列
4. **统一接口**：一套 API 服务所有频道，通过 channel_code 区分
5. **动态前端**：前端根据频道配置动态渲染，一套前端代码支持所有频道

可扩展架构的关键是"把变化的部分配置化，把不变的部分抽象成统一接口"。垂直频道的差异主要在配置（主题、字段、功能），核心流程（发布职位、搜索、投递）是一样的，所以适合用配置化方案。
