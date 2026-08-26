---
title: "Elasticsearch 测试环境集群运维笔记：分片策略与索引生命周期管理"
date: 2022-10-15T11:00:00+08:00
draft: false
tags: ["Elasticsearch", "运维", "分片", "索引生命周期", "性能调优"]
categories: ["运维"]
summary: "Elasticsearch 测试环境集群运维实践笔记，涵盖分片策略设计、索引生命周期管理、冷热分离、备份恢复，以及日常运维中的常见问题排查。"
---

Elasticsearch 集群搭起来容易，运维好难。测试环境的 ES 集群跑了一年多，踩了不少坑——分片过多导致集群状态 yellow、索引膨胀磁盘满、冷数据占着热节点资源。今天把运维实践整理成笔记，给用 ES 的朋友做个参考。

## 一、分片策略

### 1.1 分片数不是越多越好

早期建索引时图省事，所有索引都设 5 个主分片 + 1 个副本。结果索引多了之后，集群有几千个分片，每个分片都有额外的内存开销（集群元数据、分片状态），集群状态经常 yellow，恢复慢。

正确的分片数估算：
- 单分片数据量建议 20-50GB
- 分片数 = 预估总数据量 / 30GB
- 小索引（<10GB）1个主分片就够

```json
// 大索引（职位搜索，预计50GB）
PUT /job
{
  "settings": {
    "number_of_shards": 3,
    "number_of_replicas": 1
  }
}

// 小索引（操作日志，预计5GB）
PUT /operation_log
{
  "settings": {
    "number_of_shards": 1,
    "number_of_replicas": 1
  }
}
```

### 1.2 分片均衡

集群节点配置不一样时，分片分配不均会导致某些节点压力大。用分片分配过滤控制：

```json
PUT /job/_settings
{
  "index.routing.allocation.total_shards_per_node": 2
}
```

限制每个节点最多分配 2 个该索引的分片，避免热点。

## 二、索引生命周期管理（ILM）

ES 7.x 自带 ILM（Index Lifecycle Management），自动管理索引的生命周期，不用自己写脚本删索引。

### 2.1 ILM 策略

```json
PUT _ilm/policy/log_policy
{
  "policy": {
    "phases": {
      "hot": {
        "actions": {
          "rollover": {
            "max_size": "50GB",
            "max_age": "7d"
          }
        }
      },
      "warm": {
        "min_age": "7d",
        "actions": {
          "shrink": {"number_of_shards": 1},
          "forcemerge": {"max_num_segments": 1}
        }
      },
      "cold": {
        "min_age": "30d",
        "actions": {
          "allocate": {
            "require": {"data": "cold"}
          }
        }
      },
      "delete": {
        "min_age": "90d",
        "actions": {
          "delete": {}
        }
      }
    }
  }
}
```

四个阶段：
- **hot**：热数据，读写频繁，rollover 自动创建新索引
- **warm**：7天后转 warm，收缩分片数、合并段，减少资源占用
- **cold**：30天后转 cold，迁移到冷节点（低配机器）
- **delete**：90天后自动删除

### 2.2 索引模板关联 ILM

```json
PUT _index_template/log_template
{
  "index_patterns": ["operation_log-*"],
  "template": {
    "settings": {
      "number_of_shards": 3,
      "number_of_replicas": 1,
      "index.lifecycle.name": "log_policy",
      "index.lifecycle.rollover_alias": "operation_log"
    }
  }
}
```

用索引模板，新建索引自动应用 ILM 策略，不用每个索引单独配置。

## 三、冷热分离

热节点（高配，SSD）存近期数据，冷节点（低配，机械盘）存历史数据，降低成本。

### 3.1 节点标记

```bash
# 启动时指定节点属性
bin/elasticsearch -Enode.attr.data=hot
bin/elasticsearch -Enode.attr.data=cold
```

### 3.2 索引分配

```json
PUT /operation_log-2022.10/_settings
{
  "index.routing.allocation.require.data": "cold"
}
```

ILM 的 cold 阶段会自动执行这个操作，把索引迁移到冷节点。

## 四、备份恢复

### 4.1 快照仓库

```json
PUT _snapshot/es_backup
{
  "type": "fs",
  "settings": {
    "location": "/data/es_backup",
    "compress": true
  }
}
```

### 4.2 自动快照

用 Curator 或 cron 定时创建快照：

```bash
# 每天凌晨备份
curl -X PUT "localhost:9200/_snapshot/es_backup/snapshot_$(date +%Y%m%d)?wait_for_completion=true"
```

### 4.3 恢复

```bash
# 恢复指定索引
curl -X POST "localhost:9200/_snapshot/es_backup/snapshot_20221015/_restore" -H 'Content-Type: application/json' -d'
{
  "indices": "job",
  "ignore_unavailable": true,
  "include_global_state": false
}'
```

## 五、常见问题排查

### 5.1 集群状态 yellow

yellow 表示主分片都分配了，但有副本没分配。排查：

```bash
# 查看未分配的分片
curl "localhost:9200/_cat/shards?v&h=index,shard,prirep,state,unassigned.reason" | grep UNASSIGNED

# 查看未分配原因
curl "localhost:9200/_cluster/allocation/explain" -H 'Content-Type: application/json' -d'
{
  "index": "job",
  "shard": 0,
  "primary": false
}'
```

常见原因：磁盘满（>85%）、分片分配策略限制、节点下线。

### 5.2 查询慢

```bash
# 开启慢查询日志
PUT /job/_settings
{
  "index.search.slowlog.threshold.query.warn": "5s",
  "index.search.slowlog.threshold.query.info": "2s"
}

# 用 profile API 分析查询
POST /job/_search
{
  "profile": true,
  "query": { ... }
}
```

### 5.3 磁盘满

- 检查索引大小：`_cat/indices?v&s=store.size:desc`
- 删除无用索引
- 调整 ILM 策略，更早删除或转冷
- 扩容磁盘

## 六、总结

Elasticsearch 集群运维核心要点：

1. **分片合理**：根据数据量估算分片数，不是越多越好，单分片 20-50GB
2. **ILM 自动化**：用索引生命周期管理自动 rollover、收缩、迁移、删除，不用人工干预
3. **冷热分离**：热数据放高配节点，冷数据迁低配节点，降低成本
4. **备份不可少**：定期快照备份，关键时刻能恢复
5. **监控要到位**：集群状态、节点资源、索引大小、查询延迟，都要监控告警
6. **问题会排查**：yellow 状态、慢查询、磁盘满，这些常见问题要会快速定位

ES 运维是个持续的过程，业务在变，数据在涨，索引设计和 ILM 策略也要跟着调整。定期 review 集群状态，提前发现问题，比出了问题再救火成本低得多。
