---
title: "数据库与搜索：MySQL、Redis、Elasticsearch"
description: "存储与检索的实战笔记：MySQL 索引与分表分区、Redis 缓存与一致性、Elasticsearch 索引设计与增删改查，含踩坑与调优过程。"
date: 2026-11-01
tags: ["MySQL", "Redis", "Elasticsearch"]
ShowToc: false
ShowReadingTime: false
---

这里聚合了 **数据存储与搜索** 方向的文章。核心是三件事：数据放哪、怎么查得快、以及数据不一致时怎么收拾。

MySQL 部分偏索引设计、分表分区与慢查询治理；Redis 部分偏缓存策略、击穿雪崩与一致性取舍；Elasticsearch 部分偏索引结构、写入与查询的权衡——包括中文分词、深分页这类容易被忽略、但一上量就致命的问题。

{{< topiclist tags="MySQL,Redis,Elasticsearch" >}}
