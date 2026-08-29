---
title: "Elasticsearch 集群搭建与调优：测试环境 3 节点集群的完整部署笔记"
date: 2020-06-30T16:30:00+08:00
draft: false
tags: ["Elasticsearch", "运维", "集群搭建", "性能调优", "搜索"]
categories: ["运维"]
summary: "Elasticsearch 测试环境 3 节点集群从0到1的完整部署笔记，涵盖安装配置、索引设计、分片策略、性能调优与常见问题排查。"
---

2020年中，我们的招聘搜索要从 MySQL LIKE 查询迁移到 Elasticsearch。先在测试环境搭了个 3 节点集群做验证，踩了不少坑。今天把完整的部署和调优过程记录下来，给要搭 ES 集群的朋友做个参考。

## 一、集群规划

### 1.1 节点角色

Elasticsearch 的节点有多种角色，测试环境 3 节点的规划：

| 节点 | 角色 | 配置 |
|------|------|------|
| es-node-1 | master + data + ingest | 4C8G |
| es-node-2 | master + data + ingest | 4C8G |
| es-node-3 | master + data + ingest | 4C8G |

测试环境资源有限，三个节点都兼做 master 和 data。生产环境建议 master 节点和 data 节点分离，master 节点不配 data 角色，稳定性更好。

### 1.2 版本选择

选了 Elasticsearch 7.6.2，原因：
- 7.x 是当时的稳定主流版本
- 移除了 type 概念，索引设计更简洁
- 生态成熟，插件和工具支持完善

JDK 用 ES 自带的 OpenJDK 13，不用单独装。

## 二、安装部署

### 2.1 系统准备

```bash
# 创建用户
useradd elasticsearch
passwd elasticsearch

# 目录规划
mkdir -p /data/es/data
mkdir -p /data/es/logs
chown -R elasticsearch:elasticsearch /data/es

# 系统参数调优
# /etc/security/limits.conf
elasticsearch soft nofile 65536
elasticsearch hard nofile 65536
elasticsearch soft nproc 4096
elasticsearch hard nproc 4096
elasticsearch soft memlock unlimited
elasticsearch hard memlock unlimited

# /etc/sysctl.conf
vm.max_map_count = 262144
```

`vm.max_map_count` 这个参数很重要，ES 启动时会检查，不设的话会报错。`nofile` 也要调大，ES 需要打开大量文件。

### 2.2 下载安装

```bash
# 下载
su - elasticsearch
wget https://artifacts.elastic.co/downloads/elasticsearch/elasticsearch-7.6.2-linux-x86_64.tar.gz
tar -xzf elasticsearch-7.6.2-linux-x86_64.tar.gz
mv elasticsearch-7.6.2 /usr/local/elasticsearch
```

### 2.3 配置文件

`config/elasticsearch.yml`：

```yaml
# 集群名称
cluster.name: recruit-es-cluster

# 节点名称
node.name: es-node-1
node.master: true
node.data: true
node.ingest: true

# 数据和日志路径
path.data: /data/es/data
path.logs: /data/es/logs

# 内存锁定
bootstrap.memory_lock: true

# 网络绑定
network.host: 0.0.0.0
http.port: 9200
transport.port: 9300

# 集群发现
discovery.seed_hosts: ["10.0.0.1:9300", "10.0.0.2:9300", "10.0.0.3:9300"]
cluster.initial_master_nodes: ["es-node-1", "es-node-2", "es-node-3"]

# 跨域（给 head 插件用）
http.cors.enabled: true
http.cors.allow-origin: "*"

# 安全（测试环境先关了，生产环境要开）
xpack.security.enabled: false
```

三个节点的配置基本一样，只有 `node.name` 和 IP 不同。

`config/jvm.options`：

```text
# 堆内存，建议设为物理内存的一半，但不超过32GB
-Xms4g
-Xmx4g

# GC 日志
-XX:+PrintGCDetails
-XX:+PrintGCDateStamps
-XX:+PrintGCTimeStamps
-Xloggc:/data/es/logs/gc.log
```

堆内存设为 4G（机器 8G 内存的一半）。ES 的堆内存不是越大越好，超过 32GB 会禁用指针压缩，反而效率下降。一般设为物理内存的 50%，剩下的给操作系统做文件缓存（Lucene 依赖文件缓存提升性能）。

### 2.4 启动集群

```bash
# 每个节点都启动
su - elasticsearch
cd /usr/local/elasticsearch
./bin/elasticsearch -d

# 检查状态
curl http://localhost:9200/_cluster/health?pretty
```

健康状态应该是 `green`，三个节点都加入集群。

```json
{
  "cluster_name" : "recruit-es-cluster",
  "status" : "green",
  "number_of_nodes" : 3,
  "number_of_data_nodes" : 3,
  "active_primary_shards" : 0,
  "active_shards" : 0,
  "unassigned_shards" : 0
}
```

## 三、索引设计

### 3.1 职位索引

招聘搜索的核心是职位搜索，索引设计：

```json
PUT /job
{
  "settings": {
    "number_of_shards": 3,
    "number_of_replicas": 1,
    "refresh_interval": "5s",
    "analysis": {
      "analyzer": {
        "ik_max_word": {
          "type": "custom",
          "tokenizer": "ik_max_word"
        },
        "ik_smart": {
          "type": "custom",
          "tokenizer": "ik_smart"
        }
      }
    }
  },
  "mappings": {
    "properties": {
      "title": {
        "type": "text",
        "analyzer": "ik_max_word",
        "search_analyzer": "ik_smart",
        "fields": {
          "keyword": {
            "type": "keyword"
          }
        }
      },
      "company_id": {"type": "integer"},
      "company_name": {
        "type": "text",
        "analyzer": "ik_max_word"
      },
      "city_id": {"type": "integer"},
      "city_name": {"type": "keyword"},
      "salary_min": {"type": "integer"},
      "salary_max": {"type": "integer"},
      "experience": {"type": "keyword"},
      "education": {"type": "keyword"},
      "job_category": {"type": "integer"},
      "tags": {"type": "keyword"},
      "description": {
        "type": "text",
        "analyzer": "ik_max_word"
      },
      "status": {"type": "byte"},
      "created_at": {"type": "date"},
      "updated_at": {"type": "date"}
    }
  }
}
```

关键点：
- `number_of_shards: 3`：3 个主分片，和数据节点数一致
- `number_of_replicas: 1`：1 个副本，保证高可用
- `refresh_interval: 5s`：5 秒刷新一次，平衡实时性和写入性能
- 中文分词用 IK 插件，索引用 `ik_max_word`（最细粒度），搜索用 `ik_smart`（智能分词）
- 需要聚合和精确匹配的字段用 `keyword` 类型
- 文本字段加 `fields.keyword` 子字段，同时支持全文检索和精确匹配

### 3.2 分片策略

分片数不是越多越好。分片过多会导致：
- 集群元数据压力大
- 每个分片有额外的内存开销
- 查询时需要聚合多个分片的结果，延迟增加

分片数的估算：单分片数据量建议 20-50GB。我们的职位数据预计 500 万条，单条约 2KB，总共约 10GB，3 个分片每个 3GB 左右，完全够用。

## 四、中文分词插件 IK

ES 自带的分词器对中文支持不好，需要装 IK 分词插件。

```bash
# 安装 IK 插件（版本要和 ES 一致）
./bin/elasticsearch-plugin install https://github.com/medcl/elasticsearch-analysis-ik/releases/download/v7.6.2/elasticsearch-analysis-ik-7.6.2.zip

# 重启 ES
```

IK 有两种分词模式：
- `ik_max_word`：最细粒度拆分，适合索引时用，召回率高
- `ik_smart`：智能分词，适合搜索时用，准确率高

自定义词典：

```xml
<!-- config/analysis-ik/IKAnalyzer.cfg.xml -->
<properties>
    <comment>IK Analyzer 扩展配置</comment>
    <entry key="ext_dict">custom.dic</entry>
    <entry key="ext_stopwords">stopword.dic</entry>
</properties>
```

`custom.dic` 里放行业专有词汇，比如"前端开发"、"算法工程师"、"酒店经理"等，避免被错误拆分。

## 五、数据同步

MySQL 到 ES 的数据同步，我们用的是 Logstash + JDBC 插件，定时全量同步。测试环境先用这个方案，生产环境后来换成了 Canal 监听 binlog 做增量同步。

### 5.1 Logstash 配置

```ruby
input {
  jdbc {
    jdbc_connection_string => "jdbc:mysql://10.0.0.10:3306/recruit?useSSL=false&characterEncoding=utf8"
    jdbc_user => "es_sync"
    jdbc_password => "password"
    jdbc_driver_library => "/usr/local/logstash/mysql-connector-java-8.0.19.jar"
    jdbc_driver_class => "com.mysql.cj.jdbc.Driver"
    statement => "SELECT id, title, company_id, company_name, city_id, city_name, salary_min, salary_max, experience, education, job_category, description, status, created_at, updated_at FROM job WHERE updated_at >= :sql_last_value"
    schedule => "*/5 * * * *"
    record_last_run => true
    use_column_value => true
    tracking_column => "updated_at"
    tracking_column_type => "timestamp"
  }
}

filter {
  mutate {
    remove_field => ["@version", "@timestamp"]
  }
}

output {
  elasticsearch {
    hosts => ["http://10.0.0.1:9200", "http://10.0.0.2:9200", "http://10.0.0.3:9200"]
    index => "job"
    document_id => "%{id}"
  }
}
```

每 5 分钟同步一次增量数据，用 `updated_at` 做水位线。`document_id` 用 MySQL 的主键，保证同步幂等。

## 六、搜索查询

### 6.1 基础搜索

```json
POST /job/_search
{
  "query": {
    "bool": {
      "must": [
        {
          "multi_match": {
            "query": "前端开发",
            "fields": ["title^3", "company_name^2", "description"],
            "type": "best_fields"
          }
        }
      ],
      "filter": [
        {"term": {"status": 1}},
        {"term": {"city_id": 2}},
        {"range": {"salary_max": {"gte": 10000}}}
      ]
    }
  },
  "sort": [
    {"_score": "desc"},
    {"created_at": "desc"}
  ],
  "from": 0,
  "size": 20,
  "highlight": {
    "fields": {
      "title": {},
      "description": {}
    }
  }
}
```

关键点：
- `multi_match` 多字段匹配，标题权重最高（^3），公司名次之（^2）
- `filter` 上下文不计算相关性得分，适合精确过滤，性能更好
- `sort` 先按相关性得分，再按发布时间
- `highlight` 高亮匹配关键词

### 6.2 聚合统计

按城市统计职位数：

```json
POST /job/_search
{
  "size": 0,
  "aggs": {
    "by_city": {
      "terms": {
        "field": "city_name",
        "size": 50
      }
    },
    "salary_stats": {
      "stats": {
        "field": "salary_min"
      }
    }
  }
}
```

## 七、性能调优

### 7.1 写入优化

```json
PUT /job/_settings
{
  "index.refresh_interval": "30s",
  "index.number_of_replicas": 0,
  "index.translog.durability": "async"
}
```

大批量导入数据时：
- 关闭副本（`number_of_replicas: 0`），导入完再开
- 延长刷新间隔（`refresh_interval: 30s`）
- 异步 translog，提升写入性能

导入完成后恢复正常设置：

```json
PUT /job/_settings
{
  "index.refresh_interval": "5s",
  "index.number_of_replicas": 1
}
```

然后强制刷新和段合并：

```bash
POST /job/_refresh
POST /job/_forcemerge?max_num_segments=1
```

### 7.2 查询优化

- 避免 `match_all` + 深度分页，用 `search_after` 替代
- 聚合查询加 `size` 限制，不要聚合所有数据
- 用 `filter` 上下文替代 `must` 做精确过滤
- 避免脚本查询，性能差
- 热数据和冷数据分开索引，冷数据可以减少副本

### 7.3 系统调优

```bash
# 关闭 swap
swapoff -a
# /etc/fstab 里注释掉 swap 行

# 文件系统用 ext4 或 xfs，不要用 btrfs
# 挂载时加 noatime 选项
mount -o remount,noatime /data
```

## 八、常见问题排查

### 8.1 集群状态 yellow

yellow 表示主分片都分配了，但有副本没分配。常见原因：
- 只有一个节点，副本无法分配（单节点集群设 `number_of_replicas: 0`）
- 磁盘空间不足（超过 85% 会停止分配）
- 分片分配策略限制

查看未分配原因：

```bash
GET /_cluster/allocation/explain
```

### 8.2 节点经常 OOM

- 检查堆内存设置是否合理（不要超过 32GB）
- 检查是否有大查询（聚合大量数据）
- 看 GC 日志，是否频繁 Full GC
- 调大机器内存或减少分片数

### 8.3 查询慢

- 用 `_profile` API 分析查询耗时
- 检查是否走了索引（`keyword` 字段用 `term`，`text` 字段用 `match`）
- 检查分片数是否过多
- 看慢查询日志，优化高频慢查询

```bash
# 开启慢查询日志
PUT /job/_settings
{
  "index.search.slowlog.threshold.query.warn": "5s",
  "index.search.slowlog.threshold.query.info": "2s",
  "index.search.slowlog.threshold.fetch.warn": "1s"
}
```

## 九、总结

Elasticsearch 集群搭建的核心要点：

1. **系统准备**：`vm.max_map_count`、`nofile`、内存锁定这些参数必须配，否则启动有问题
2. **节点规划**：生产环境 master 和 data 分离，测试环境可以合并
3. **索引设计**：分片数根据数据量估算，单分片 20-50GB 为宜；字段类型要选对，`text` 用于全文检索，`keyword` 用于聚合和精确匹配
4. **中文分词**：IK 插件必备，索引用 `ik_max_word`，搜索用 `ik_smart`
5. **数据同步**：Logstash 适合定时同步，Canal 适合实时增量同步
6. **性能调优**：写入时关副本、延长刷新间隔；查询用 filter 上下文、避免深度分页
7. **监控告警**：集群健康状态、节点 CPU/内存、磁盘使用率、查询延迟都要监控

这个测试集群后来验证通过，生产环境搭了个 6 节点的集群（3 master + 3 data），支撑了招聘搜索的上线。ES 是个强大但复杂的系统，需要持续学习和调优。这篇笔记只是入门，深入的话还要研究 Lucene 底层原理、分片路由、段合并等核心概念。
