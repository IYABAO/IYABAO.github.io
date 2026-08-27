---
title: "向量数据库选型：Milvus vs Pinecone vs Weaviate vs pgvector"
date: 2025-05-08T10:00:00+08:00
draft: false
tags: ["向量数据库", "Milvus", "Pinecone", "Weaviate", "pgvector", "RAG", "AI基础设施"]
categories: ["AI架构"]
summary: "四款主流向量数据库的深度对比，Milvus、Pinecone、Weaviate、pgvector 的架构、性能、功能、部署方式、成本，以及在 RAG 场景下的选型实践和压测数据。"
---

做 RAG 和 AI 应用，向量数据库是核心基础设施。2025年向量数据库赛道已经很成熟了，主流选项有 Milvus、Pinecone、Weaviate、pgvector，各有特点。我们在做招聘知识库 RAG 时做了深度调研和压测，今天把选型经验分享出来。

## 一、为什么需要向量数据库

传统数据库存的是结构化数据，按精确匹配或范围查询。向量数据库存的是高维向量（Embedding），按相似度检索——给一个查询向量，返回最相似的 top_k 个向量。

这是大模型应用的基础能力：
- RAG 检索相关文档
- 推荐系统找相似物品
- 图片/音频/视频的相似检索
- 去重（找相似向量判断重复）

## 二、四款向量数据库对比

### 1. Milvus

**定位**：开源、云原生、企业级向量数据库，LF AI & Data 基金会毕业项目。

**架构**：
- 存算分离架构，数据存在对象存储（S3/MinIO），计算层无状态
- 支持分布式部署，可水平扩展
- 支持多种索引：HNSW、IVF_FLAT、IVF_PQ、DiskANN、SCANN
- 支持标量过滤（混合查询）

**部署方式**：
- 单机版（Milvus Lite）：Python pip 安装，适合开发测试
- 集群版：Docker Compose / K8s（Milvus Operator），生产环境

**优点**：
- 开源免费，社区活跃，中文文档完善
- 性能强，支持十亿级向量，分布式扩展
- 功能全面，支持多种索引、标量过滤、分区、TTL
- 云原生，K8s 部署友好
- 有国内团队（Zilliz）支持，企业版有技术支持

**缺点**：
- 组件多，运维复杂（etcd、MinIO、Pulsar/Kafka 等依赖）
- 单机版功能有限，生产必须集群版
- 内存占用高，全量索引在内存里

**适用场景**：大规模向量数据（千万级以上）、需要分布式扩展、有运维能力、不想被云厂商锁定。

---

### 2. Pinecone

**定位**：全托管向量数据库 SaaS，无需运维，开箱即用。

**架构**：
- 全托管服务，用户不用管基础设施
- 自动扩缩容，根据数据量和查询量自动调整
- 支持 HNSW 索引
- 支持命名空间（namespace）隔离数据

**部署方式**：
- 纯 SaaS，注册账号即用，API 调用
- 支持 AWS/GCP/Azure 多区域部署

**优点**：
- 零运维，开箱即用，5分钟接入
- 性能稳定，SLA 保障
- 自动扩缩容，不用关心容量规划
-  API 简单，SDK 完善（Python/Node/Java/Go）
- 企业级安全（SOC2、VPC 对等）

**缺点**：
- 闭源，数据存在 Pinecone，有厂商锁定风险
- 成本高，按 pod 数量和存储计费，大规模数据很贵
- 国内访问延迟高（没有国内节点）
- 功能相对少，不支持自定义索引参数
- 标量过滤能力弱

**适用场景**：创业公司快速验证、不想运维、数据量中等、海外业务。

---

### 3. Weaviate

**定位**：开源、模块化、AI 原生向量数据库，内置 Embedding 和 Rerank 模块。

**架构**：
- 支持单机和分布式部署
- 模块化设计，内置 text2vec（OpenAI/Cohere/HuggingFace）、generative（GPT/Cohere）、rerank 模块
- 支持 HNSW 索引
- 支持 GraphQL 和 REST API
- 支持标量过滤、聚合查询

**部署方式**：
- Docker Compose 单机部署
- K8s 集群部署（Weaviate Operator）
- Weaviate Cloud Services（WCS）全托管

**优点**：
- 开源，社区活跃
- AI 原生，内置 Embedding 和生成模块，不用自己调模型
- 模块化设计，可插拔
- API 友好，GraphQL 查询灵活
- 支持混合检索（向量 + BM25）
- 有全托管云服务，也可自托管

**缺点**：
- 分布式部署不如 Milvus 成熟，大规模性能一般
- 内存占用高
- 中文社区和文档相对少
- 内置模块和自定义模型集成有学习成本

**适用场景**：需要内置 AI 能力、快速搭建 RAG、中小规模数据、喜欢模块化设计。

---

### 4. pgvector

**定位**：PostgreSQL 扩展，在关系型数据库里增加向量检索能力。

**架构**：
- PostgreSQL 扩展，安装即用
- 支持 IVFFlat 和 HNSW 索引
- 向量和业务数据存在同一个数据库，支持事务和 JOIN
- 支持标量过滤（天然支持，因为就是 PostgreSQL）

**部署方式**：
- PostgreSQL 安装 create extension vector
- 云数据库（RDS、Supabase、Neon 等）大多已支持

**优点**：
- 最简单，不用引入新数据库，已有 PostgreSQL 就能用
- 向量和业务数据一起存，支持事务、JOIN、复杂过滤
- 运维成本为零（已有 PG 的话）
- 学习成本低，SQL 查询，不用学新 API
- 成本低，不需要额外基础设施

**缺点**：
- 性能有限，不适合大规模向量（百万级以上性能下降明显）
- 索引功能少，只有 IVFFlat 和 HNSW
- 不支持分布式扩展（受限于 PostgreSQL 单机）
- 高并发查询性能不如专用向量数据库
- 向量检索和业务查询抢资源

**适用场景**：中小规模数据（百万级以内）、已有 PostgreSQL、向量检索需求简单、不想引入新组件。

---

## 三、详细对比表

| 维度 | Milvus | Pinecone | Weaviate | pgvector |
|------|--------|----------|----------|----------|
| 开源 | ✅ Apache 2.0 | ❌ 闭源 | ✅ BSD-3 | ✅ PostgreSQL 扩展 |
| 部署 | 自托管/云(Zilliz) | 纯 SaaS | 自托管/云(WCS) | PostgreSQL 扩展 |
| 运维复杂度 | 高 | 零 | 中 | 低 |
| 数据规模 | 十亿级 | 百万-十亿 | 千万级 | 百万级 |
| 分布式 | ✅ 原生 | ✅ 托管 | ✅ | ❌ |
| 索引类型 | HNSW/IVF/PQ/DiskANN/SCANN | HNSW | HNSW | IVFFlat/HNSW |
| 标量过滤 | ✅ 强 | ✅ 弱 | ✅ 强 | ✅ 极强(SQL) |
| 混合检索 | ✅ | ❌ | ✅(内置BM25) | ✅(自己写) |
| 内置AI模块 | ❌ | ❌ | ✅(Embedding/Generative/Rerank) | ❌ |
| API | gRPC/REST/PythonSDK | REST/PythonSDK | GraphQL/REST/PythonSDK | SQL |
| 成本 | 自托管免费/云服务收费 | 高(pod计费) | 自托管免费/云收费 | 低(已有PG) |
| 国内访问 | ✅ 可自托管 | ❌ 延迟高 | ✅ 可自托管 | ✅ |
| 社区活跃度 | 高 | 中 | 中高 | 高(PostgreSQL生态) |
| 学习成本 | 中 | 低 | 中 | 低 |

## 四、我们的压测数据

在招聘知识库场景（500万文档 chunk，1024维向量）做了压测：

| 指标 | Milvus(集群) | Weaviate(单机) | pgvector(单机) |
|------|-------------|---------------|----------------|
| 索引构建时间 | 2小时 | 5小时 | 8小时 |
| 内存占用 | 32GB | 48GB | 64GB |
| P50 查询延迟 | 8ms | 15ms | 25ms |
| P99 查询延迟 | 25ms | 60ms | 120ms |
| 并发 QPS | 5000+ | 2000 | 800 |
| 召回率@10 | 95% | 93% | 90% |

测试环境：相同服务器配置，HNSW 索引（M=16, efConstruction=256, ef=64）。

结论：500万向量规模下，Milvus 性能明显领先，pgvector 已经有点吃力了。

## 五、选型建议

### 按数据规模选

- **10万以内**：pgvector，最简单，不用引入新东西
- **10万-100万**：pgvector 或 Weaviate，都能扛住
- **100万-1000万**：Milvus 或 Weaviate，pgvector 开始吃力
- **1000万以上**：Milvus 集群版，分布式扩展是必须的

### 按团队能力选

- **没有运维能力，想快速验证**：Pinecone 或 Weaviate Cloud
- **有 K8s 运维能力，数据量大**：Milvus 集群版
- **已有 PostgreSQL，数据量不大**：pgvector
- **需要内置 AI 能力，不想自己调模型**：Weaviate

### 按业务场景选

- **RAG 知识库**：Milvus（大规模）或 pgvector（小规模），配合重排序
- **推荐系统**：Milvus，高性能高并发
- **多模态检索**：Milvus 或 Weaviate
- **创业公司 MVP**：Pinecone 或 pgvector，快速上线
- **国内业务**：Milvus 自托管或 Zilliz Cloud（国内有节点），Pinecone 延迟高不推荐

## 六、我们的最终选型

招聘知识库 RAG 场景：
- 数据量：500万 chunk，且持续增长
- 并发：峰值 1000 QPS
- 团队：有 K8s 运维能力
- 国内业务，不能用 Pinecone

**最终选 Milvus 集群版**，部署在 K8s 上：
- 3 个 query node + 2 个 data node + 3 个 index node
- 数据存在 MinIO（对象存储）
- 用 HNSW 索引，M=16, efConstruction=256
- 按业务类型分 collection（制度库、岗位库、简历库）
- 配合 bge-reranker 做重排序

同时在一些小场景（如内部工具的小知识库）用 pgvector，不用每个场景都上 Milvus。

## 七、踩坑经验

1. **索引参数很重要**：HNSW 的 M 和 efConstruction 直接影响召回率和内存。M 越大召回越高但内存越大，建议 M=16-32，efConstruction=128-512
2. **ef 参数影响查询延迟**：查询时的 ef 参数越大召回越高但延迟越高，在线查询建议 ef=64-128，离线批量查询可以调高
3. **内存规划要留余量**：全量 HNSW 索引在内存里，500万1024维向量约占 40GB 内存。实际使用要留 2 倍余量，防止查询时内存暴涨
4. **标量过滤下推**：Milvus 的标量过滤可以下推到索引层，比先检索再过滤快很多。要确保过滤字段建了标量索引
5. **冷热数据分离**：历史数据查询频率低，可以用 DiskANN 索引存在磁盘上，热数据用 HNSW 在内存里，降低成本
6. **不要盲目上向量数据库**：数据量小的时候（几万条），用 PostgreSQL 的 `ORDER BY embedding <=> query_vector` 暴力计算都够了，不用上向量数据库
7. **Embedding 模型和向量数据库匹配**：不同 Embedding 模型生成的向量不能混用，一个 collection 里只能存同一种模型生成的向量。换模型要重建索引

## 八、总结

向量数据库选型核心：

1. **数据规模是第一考量**：百万级以内 pgvector 够用，千万级以上 Milvus，中间档 Weaviate
2. **运维能力决定部署方式**：能运维就自托管 Milvus/Weaviate，不能就用 SaaS
3. **国内业务慎选 Pinecone**：延迟高、数据出境合规问题，优先自托管或国内云服务
4. **不要过度设计**：小数据量用 pgvector，简单可靠，等数据量上来再迁移
5. **索引参数调优**：HNSW 的 M、efConstruction、ef 三个参数要根据场景调，默认值不一定最优
6. **配合重排序**：向量检索召回 + Cross-Encoder 重排序，效果比纯向量检索好很多
7. **预留扩展空间**：向量数据增长很快，选型时要考虑 1-2 年后的数据量，避免频繁迁移

向量数据库是 AI 应用的基础设施，选型要结合数据规模、团队能力、业务场景综合考虑。没有最好的，只有最适合的。建议从简单方案开始（pgvector），跑通业务后再根据数据量和性能需求迁移到更专业的向量数据库。
