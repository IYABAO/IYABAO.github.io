---
title: "ELK 日志中台：从采集到告警全流程"
date: 2024-02-28T09:00:00+08:00
lastmod: 2024-02-28T09:00:00+08:00
draft: false
author: IYABAO
tags:
  - ELK
  - Elasticsearch
  - 日志
  - 可观测
categories:
  - 技术
summary: "服务拆成 20 个，排障却要登录 20 台机器 grep。ELK 日志中台把采集、解析、存储、检索、告警串成全流程，从此查日志是搜索不是翻文件。"
---

# ELK 日志中台：从采集到告警全流程

微服务化之后，排障体验直线下降：一个请求跨 5 个服务，报错分散在 5 台机器 5 个日志文件里。我们花了三周搭起 ELK 日志中台，从此查一条链路日志就是一次搜索。

## 一、整体架构

```
服务 A ── Filebeat ──┐
服务 B ── Filebeat ──┼──► Logstash ──► Elasticsearch ──► Kibana
服务 C ── Filebeat ──┘        │              │
                              │              └──► 索引生命周期(ILM)
                              └──► 告警规则
```

- **Filebeat**：轻量采集，装在每个 Pod（sidecar）/节点，只做搬运
- **Logstash**：解析、清洗、字段标准化（可以换成轻量的 pipeline）
- **Elasticsearch**：存储 + 检索，索引按天滚动 + ILM 生命周期
- **Kibana**：检索 UI + 可视化 + 告警（ElastAlert 或 Kibana Alerting）

## 二、采集层：Filebeat 配置要点

```yaml
filebeat.inputs:
- type: container
  paths:
    - /var/log/containers/*.log
  processors:
    - add_kubernetes_metadata:      # 自动带 K8s 元数据
        host: ${NODE_NAME}
    - dissect:                       # 解析 JSON 日志
        tokenizer: "%{time} %{level} %{msg}"
```

**关键设计**：应用日志统一输出 **JSON 格式**（`{"time":"...","level":"info","trace_id":"...","msg":"..."}`），Filebeat 直接解析字段，Logstash 就不用做正则猜格式。**先统一日志格式，再谈中台**——这是我们踩坑后第一个定的规矩。

## 三、解析层：字段标准化

Logstash pipeline 统一做三件事：

1. **时间标准化**：所有日志时间统一转 ISO8601 存 `@timestamp`
2. **字段重命名**：`msg` → `message`，`trace_id` → `traceId`，全局统一
3. **补充环境标签**：`env`（prod/staging）、`service`、`pod` 从 K8s metadata 补

```
field 标准（全局唯一）：
  traceId   调用链 ID
  requestId 单请求 ID
  service   服务名
  env       环境
  level     debug/info/warn/error
  message   日志正文
  latencyMs 接口耗时（有则填）
```

## 四、存储层：索引设计与 ILM

```json
// 索引模板
{
  "index_patterns": ["app-logs-*"],
  "settings": {
    "number_of_shards": 3,
    "number_of_replicas": 1,
    "lifecycle": { "name": "log-ilm" }
  },
  "mappings": {
    "properties": {
      "traceId":  { "type": "keyword" },
      "message":  { "type": "text", "analyzer": "ik_max_word" },
      "latencyMs":{ "type": "long" }
    }
  }
}
```

**ILM 生命周期**：

| 阶段 | 时间 | 动作 |
|---|---|---|
| hot | 第 0-3 天 | 读写 |
| warm | 3-15 天 | 只读，forcemerge 压缩 |
| cold | 15-60 天 | 冷存储，冻结 |
| delete | 60 天 | 删除 |

**索引别名只给一个**（`app-logs`），应用查询走别名，滚动对上层透明。

## 五、检索：链路追踪的核心

一条业务报错怎么查：

```
1. Kibana 搜 level:error + service:delivery + @timestamp:最近1h
2. 拿到报错日志的 traceId
3. 按 traceId 全索引搜 → 该请求经过的所有服务日志全出来
4. 按 @timestamp 排序 → 还原调用链
```

**这就是统一 traceId 字段的价值**：跨服务排障从"grep 20 台机器"变成"一次搜索"。

## 六、告警：从被动到主动

Kibana Alerting 配规则：

- **错误率告警**：`level:error` 数量在 5 分钟内 > 阈值
- **延迟告警**：`latencyMs` p99 > 1s 持续 10 分钟
- **静默规则**：维护窗口静默，避免误报

告警打 Webhook → 企业微信/钉钉群，附 Kibana 检索链接，**收到告警点进去就是日志**，不用再查半天。

## 七、踩坑记录

1. **日志量爆炸**：Debug 日志全量收集，ES 磁盘三天爆掉 → 生产只收 info 以上，debug 按需开
2. **时间戳乱**：不同语言服务时区不一致 → Logstash 统一转 UTC 存，Kibana 展示转本地
3. **索引分片过多**：早期一天 30 个索引 3 分片 = 90 分片，集群性能崩 → 按业务域合并索引，控制总分片数
4. **Kibana 慢**：没有 date filter 的全索引查询巨慢 → 规范查询必须带时间范围

## 总结

日志中台的三板斧：

1. **先标准化**：JSON 结构化输出 + 统一字段，没有标准就没有检索
2. **生命周期**：ILM 管存储成本，hot/warm/cold 分层
3. **traceId 贯穿**：跨服务排障就靠它，没有 traceId 的日志中台是数据仓库不是排障工具

**日志中台不是搭完就完，是排障效率的杠杆——每多一个服务，收益就放大一次。**
