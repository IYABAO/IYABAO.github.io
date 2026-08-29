---
title: "ELK 日志中台搭建实践：从 Filebeat 到 Kibana 的全链路日志方案"
date: 2023-12-10T10:00:00+08:00
draft: false
tags: ["ELK", "日志", "Filebeat", "Elasticsearch", "Kibana", "可观测性"]
categories: ["运维"]
summary: "ELK 日志中台搭建实践，涵盖 Filebeat 日志采集、Logstash 过滤清洗、Elasticsearch 存储索引、Kibana 可视化分析，解决微服务架构下日志分散、排查困难的问题。"
keywords: ["ELK", "日志中台", "Filebeat", "Kibana", "可观测性"]
---

微服务架构下，日志分散在各个服务的各个 Pod 里，出问题排查要登到各个机器上翻日志，效率极低。2023年底搭了 ELK 日志中台，统一采集、存储、分析所有服务的日志。今天把搭建实践分享出来。

## 一、架构

```
应用日志 → Filebeat（DaemonSet）→ Logstash（过滤清洗）→ Elasticsearch（存储索引）→ Kibana（可视化分析）
```

- **Filebeat**：轻量日志采集器，以 DaemonSet 方式部署在每个 K8s 节点
- **Logstash**：日志过滤、清洗、转换，把非结构化日志转成结构化
- **Elasticsearch**：日志存储和检索，支持全文搜索和聚合分析
- **Kibana**：日志可视化界面，支持搜索、过滤、图表、仪表盘

## 二、Filebeat 部署

K8s 环境用 DaemonSet 部署，每个节点一个 Filebeat：

```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: filebeat
  namespace: logging
spec:
  selector:
    matchLabels:
      app: filebeat
  template:
    metadata:
      labels:
        app: filebeat
    spec:
      containers:
      - name: filebeat
        image: elastic/filebeat:7.17.0
        volumeMounts:
        - name: config
          mountPath: /usr/share/filebeat/filebeat.yml
          subPath: filebeat.yml
        - name: varlog
          mountPath: /var/log
        - name: dockercontainers
          mountPath: /var/lib/docker/containers
          readOnly: true
      volumes:
      - name: config
        configMap:
          name: filebeat-config
      - name: varlog
        hostPath:
          path: /var/log
      - name: dockercontainers
        hostPath:
          path: /var/lib/docker/containers
```

Filebeat 配置：

```yaml
filebeat.inputs:
- type: container
  paths:
    - /var/log/containers/*.log
  processors:
    - add_kubernetes_metadata:
        host: ${NODE_NAME}
        matchers:
        - logs_path:
            logs_path: "/var/log/containers/"

output.logstash:
  hosts: ["logstash:5044"]
```

## 三、Logstash 过滤

Logstash 把非结构化日志转成结构化：

```ruby
input {
  beats {
    port => 5044
  }
}

filter {
  # 解析 JSON 格式日志
  if [kubernetes][container][name] == "php-api" {
    json {
      source => "message"
      target => "parsed"
    }
    mutate {
      add_field => {
        "service" => "php-api"
        "level" => "%{[parsed][level]}"
        "trace_id" => "%{[parsed][trace_id]}"
      }
      remove_field => ["message", "parsed"]
    }
  }

  # 解析 Nginx access log
  if [kubernetes][container][name] == "nginx" {
    grok {
      match => { "message" => "%{COMBINEDAPACHELOG}" }
    }
    mutate {
      convert => { "bytes" => "integer" }
      convert => { "response" => "integer" }
    }
  }

  # 统一时间字段
  date {
    match => ["@timestamp", "ISO8601"]
    target => "@timestamp"
  }
}

output {
  elasticsearch {
    hosts => ["elasticsearch:9200"]
    index => "logs-%{[kubernetes][namespace]}-%{+YYYY.MM.dd}"
  }
}
```

## 四、Elasticsearch 索引管理

按命名空间 + 日期建索引，方便管理和过期删除：

```json
PUT _index_template/logs_template
{
  "index_patterns": ["logs-*"],
  "template": {
    "settings": {
      "number_of_shards": 3,
      "number_of_replicas": 1,
      "index.lifecycle.name": "logs_policy"
    },
    "mappings": {
      "properties": {
        "@timestamp": {"type": "date"},
        "service": {"type": "keyword"},
        "level": {"type": "keyword"},
        "trace_id": {"type": "keyword"},
        "message": {"type": "text"},
        "kubernetes": {
          "properties": {
            "namespace": {"type": "keyword"},
            "pod": {"type": "keyword"},
            "container": {"type": "keyword"}
          }
        }
      }
    }
  }
}
```

ILM 策略，30天后转冷节点，90天后删除：

```json
PUT _ilm/policy/logs_policy
{
  "policy": {
    "phases": {
      "hot": {"actions": {"rollover": {"max_size": "50GB", "max_age": "1d"}}},
      "warm": {"min_age": "7d", "actions": {"forcemerge": {"max_num_segments": 1}}},
      "cold": {"min_age": "30d", "actions": {"allocate": {"require": {"data": "cold"}}}},
      "delete": {"min_age": "90d", "actions": {"delete": {}}}
    }
  }
}
```

## 五、Kibana 仪表盘

常用仪表盘：
1. **错误日志监控**：按服务、级别统计错误数，错误率趋势图
2. **接口性能分析**：按接口统计 P50/P95/P99 响应时间，慢查询 Top 10
3. **业务链路追踪**：按 trace_id 搜索全链路日志
4. **资源使用监控**：Pod CPU/内存/网络指标

## 六、踩坑经验

1. **Filebeat 日志重复**：Filebeat 重启后可能重复发送日志，用 Logstash 的 fingerprint 过滤器去重
2. **日志量大 ES 压力大**：高流量服务日志量巨大，ES 写入压力大。用采样（只采集 10% 的 INFO 日志，ERROR 全采）或直接输出到 Kafka 缓冲
3. **多Line日志解析**：Java/PHP 的异常堆栈是多行，Filebeat 要配置 multiline 把多行合并成一条
4. **Kibana 查询慢**：时间范围选太大查询慢，默认限制最近 15 分钟，提醒用户缩小范围

## 七、总结

ELK 日志中台搭建核心：

1. **采集层**：Filebeat DaemonSet 部署，轻量高效
2. **清洗层**：Logstash 过滤转换，非结构化转结构化
3. **存储层**：ES 按命名空间+日期建索引，ILM 自动管理生命周期
4. **展示层**：Kibana 仪表盘，错误监控、性能分析、链路追踪
5. **性能优化**：采样、多行合并、去重、冷热分离
6. **告警集成**：错误率超阈值自动告警，和钉钉/邮件集成

日志中台的价值在于"快速定位问题"——以前排查问题要登机器翻日志，现在在 Kibana 里搜 trace_id 就能看到全链路日志，排查时间从几十分钟降到几分钟。可观测性是微服务架构的基础，日志、指标、链路追踪三者缺一不可。
