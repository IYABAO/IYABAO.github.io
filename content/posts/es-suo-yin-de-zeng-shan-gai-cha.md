---
title: "ES索引的增删改查"
date: 2020-09-08
draft: false
summary: "Elasticsearch 索引增删改查实战笔记：通过标准 RESTful 接口演示索引的创建、查看、更新与删除操作，汇总常用 API 与 Kibana 调试技巧，ES 日常运维必备。"
slug: "es-suo-yin-de-zeng-shan-gai-cha"
---

标准的restful接口

# 查

查看所有index, 等价于show tables;

GET \_cat/indices

GET test\_index

GET kibana\_sample\_data\_logs?include\_type\_name=true&include\_defaults=true

- aliases
- mappings
- settings

# 删

DELETE test\_index

DELETE test\_index?ignore\_unavailable=true ==> drop table xx if exists

# 增

```
PUT kibana_sample_data_ecommerce2?include_type_name=true
{
"mappings" : {
      "_doc" : {
        "properties" : {
          "@timestamp" : {
            "type" : "alias",
            "path" : "timestamp"
          },
          "agent" : {
            "type" : "text",
            "fields" : {
              "keyword" : {
                "type" : "keyword",
                "ignore_above" : 256
              }
            }
          },
          "bytes" : {
            "type" : "long"
          },
          "clientip" : {
            "type" : "ip"
          },
          "event" : {
            "properties" : {
              "dataset" : {
                "type" : "keyword"
              }
            }
          },
          "extension" : {
            "type" : "text",
            "fields" : {
              "keyword" : {
                "type" : "keyword",
                "ignore_above" : 256
              }
            }
          },
          "geo" : {
            "properties" : {
              "coordinates" : {
                "type" : "geo_point"
              },
              "dest" : {
                "type" : "keyword"
              },
              "src" : {
                "type" : "keyword"
              },
              "srcdest" : {
                "type" : "keyword"
              }
            }
          },
          "host" : {
            "type" : "text",
            "fields" : {
              "keyword" : {
                "type" : "keyword",
                "ignore_above" : 256
              }
            }
          },
          "index" : {
            "type" : "text",
            "fields" : {
              "keyword" : {
                "type" : "keyword",
                "ignore_above" : 256
              }
            }
          },
          "ip" : {
            "type" : "ip"
          },
          "machine" : {
            "properties" : {
              "os" : {
                "type" : "text",
                "fields" : {
                  "keyword" : {
                    "type" : "keyword",
                    "ignore_above" : 256
                  }
                }
              },
              "ram" : {
                "type" : "long"
              }
            }
          },
          "memory" : {
            "type" : "double"
          },
          "message" : {
            "type" : "text",
            "fields" : {
              "keyword" : {
                "type" : "keyword",
                "ignore_above" : 256
              }
            }
          },
          "phpmemory" : {
            "type" : "long"
          },
          "referer" : {
            "type" : "keyword"
          },
          "request" : {
            "type" : "text",
            "fields" : {
              "keyword" : {
                "type" : "keyword",
                "ignore_above" : 256
              }
            }
          },
          "response" : {
            "type" : "text",
            "fields" : {
              "keyword" : {
                "type" : "keyword",
                "ignore_above" : 256
              }
            }
          },
          "tags" : {
            "type" : "text",
            "fields" : {
              "keyword" : {
                "type" : "keyword",
                "ignore_above" : 256
              }
            }
          },
          "timestamp" : {
            "type" : "date"
          },
          "url" : {
            "type" : "text",
            "fields" : {
              "keyword" : {
                "type" : "keyword",
                "ignore_above" : 256
              }
            }
          },
          "utc_time" : {
            "type" : "date"
          }
        }
      }
    },
    "settings" : {
      "index" : {
        "number_of_shards" : "1",
        "auto_expand_replicas" : "0-1",
        "number_of_replicas" : "1"
      }
    }
}
```

改 reindex

```
POST _reindex?wait_for_completion=true
{
  "dest": {
    "index": "kibana_sample_data_ecommerce2"
  },
  "source": {
    "index": "kibana_sample_data_ecommerce"
  }
}
```

```
POST _aliases
{
  "actions": [
    {
      "add": {
        "index": "kibana_sample_data_ecommerce2",
        "alias": "ecommerce"
      }
    },
    {
      "remove": {
        "index": "kibana_sample_data_ecommerce",
        "alias": "ecommerce"
      }
    }
  ]
}
```

mapping

POST kibana\_sample\_data\_ecommerce2/\_mapping
{

```
"properties": {
  "agent": {
    "type": "text",
    "fields": {
      "keyword": {
        "type": "keyword",
        "ignore_above": 256
      },
      "hello":{
        "type":"keyword",
        "ignore_above": 1
      }
    }
  }
}
```

}

settings

PUT kibana\_sample\_data\_ecommerce2/\_settings
{

```
"index": {
  "auto_expand_replicas": "0-1",
  "number_of_replicas": "2"
}
```

}

直接 ==> 插入数据，

让他动态索引（dynamic mapping）得到mapping，在此基础上更改。

字段类型

## Field data types

Elasticsearch supports a number of different data types for the fields in a document:

### Core data types

- string

  [`text`](text.html), [`keyword`](keyword.html) and [`wildcard`](wildcard.html)
- [Numeric](number.html)

  `long`, `integer`, `short`, `byte`, `double`, `float`, `half_float`, `scaled_float`
- [Date](date.html)

  `date`
- [Date nanoseconds](date_nanos.html)

  `date_nanos`
- [Boolean](boolean.html)

  `boolean`
- [Binary](binary.html)

  `binary`
- [Range](range.html)

  `integer_range`, `float_range`, `long_range`, `double_range`, `date_range`, `ip_range`

### Complex data types

- [Object](object.html)

  `object` for single JSON objects
- [Nested](nested.html)

  `nested` for arrays of JSON objects

### Spatial data types

- [Geo-point](geo-point.html)

  `geo_point` for lat/lon points
- [Geo-shape](geo-shape.html)

  `geo_shape` for complex shapes like polygons
- [Point](point.html)

  `point` for arbitrary cartesian points.
- [Shape](shape.html)

  `shape` for arbitrary cartesian geometries.

### Specialised data types

- [IP](ip.html)

  `ip` for IPv4 and IPv6 addresses
- [Completion data type](search-suggesters.html#completion-suggester)

  `completion` to provide auto-complete suggestions
- [Token count](token-count.html)

  `token_count` to count the number of tokens in a string
- [`mapper-murmur3`](https://www.elastic.co/guide/en/elasticsearch/plugins/7.9/mapper-murmur3.html)

  `murmur3` to compute hashes of values at index-time and store them in the index
- [`mapper-annotated-text`](https://www.elastic.co/guide/en/elasticsearch/plugins/7.9/mapper-annotated-text.html)

  `annotated-text` to index text containing special markup (typically used for identifying named entities)
- [Percolator](percolator.html)

  Accepts queries from the query-dsl
- [Join](parent-join.html)

  Defines parent/child relation for documents within the same index
- [Rank feature](rank-feature.html)

  Record numeric feature to boost hits at query time.
- [Rank features](rank-features.html)

  Record numeric features to boost hits at query time.
- [Dense vector](dense-vector.html)

  Record dense vectors of float values.
- [Sparse vector](sparse-vector.html)

  Record sparse vectors of float values.
- [Search-as-you-type](search-as-you-type.html)

  A text-like field optimized for queries to implement as-you-type completion
- [Alias](alias.html)

  Defines an alias to an existing field.
- [Flattened](flattened.html)

  Allows an entire JSON object to be indexed as a single field.
- [Histogram](histogram.html)

  `histogram` for pre-aggregated numerical values for percentiles aggregations.
- [Constant keyword](constant-keyword.html)

  Specialization of `keyword` for the case when all documents have the same value.

### Arrays

In Elasticsearch, arrays do not require a dedicated field data type. Any field can contain zero or more values by default, however, all values in the array must be of the same data type. See [Arrays](array.html).

### Multi-fields

It is often useful to index the same field in different ways for different purposes. For instance, a `string` field could be mapped as a `text` field for full-text search, and as a `keyword` field for sorting or aggregations. Alternatively, you could index a text field with the [`standard` analyzer](analysis-standard-analyzer.html), the [`english`](analysis-lang-analyzer.html#english-analyzer) analyzer, and the [`french` analyzer](analysis-lang-analyzer.html#french-analyzer).

This is the purpose of *multi-fields*. Most data types support multi-fields via the [`fields`](multi-fields.html)parameter.

"dynamic" : "true" | "false" | "strict"

"copy\_to"

数组

多字段特性

简单提下， 下下次专门讲这块

## Analysis | Built-in analyzer

char filter

Tokenizer [必须有一个]

token filter

```
html_strip
mapping
pattern_replace
```

```
PUT my-index-000001
{
  "settings": {
    "analysis": {
      "analyzer": {
        "my_custom_analyzer": {
          "type": "custom",
          "tokenizer": "standard",
          "char_filter": [
            "html_strip"
          ],
          "filter": [
            "lowercase",
            "asciifolding"
          ]
        }
      }
    }
  }
}
```

下一篇

[### Python资源大全](https://i.plbear.com/post/python-that-is-all-about-python/)
