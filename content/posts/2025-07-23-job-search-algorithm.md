---
title: "职位搜索算法优化：从 BM25 到向量检索的混合召回方案"
date: 2025-07-23T10:00:00+08:00
draft: false
tags: ["搜索算法", "向量检索", "Elasticsearch", "BM25", "RAG", "AI"]
categories: ["算法"]
summary: "职位搜索算法从传统 BM25 到向量检索的混合召回方案优化，涵盖语义匹配、向量召回、重排序，解决同义词、语义不匹配等传统搜索痛点，搜索点击率提升 35%。"
faq:
  - question: "Elasticsearch BM25 搜索有什么局限？"
    answer: "BM25 基于关键词匹配，存在三个典型问题：同义词不匹配（搜\"前端开发\"搜不到\"Vue工程师\"）、语义不匹配（搜\"钱多事少\"搜不到\"高薪轻松\"）、拼写错误容错差。这些问题会导致召回率偏低。"
  - question: "BM25 + 向量检索的混合召回方案怎么实现？"
    answer: "思路是双路召回 + 融合排序：一路走 ES BM25 关键词召回，另一路走向量检索做语义召回，两路结果通过权重融合（如 RRF/加权分数）统一排序。既保留精确关键词匹配，又补足语义泛化能力。"
  - question: "向量检索在职位搜索里怎么落地？"
    answer: "把职位标题、技能标签、JD 描述向量化存入向量索引，查询时将用户 query 也向量化检索相似职位；配合 BM25 做混合召回，可显著提升同义表达和语义匹配场景下的搜索体验。"

---

招聘平台的职位搜索最早用 Elasticsearch 的 BM25 算法，基于关键词匹配。但用户搜索"前端开发"时，标题写"Vue工程师"的职位搜不到，因为没有共同关键词。2025年7月做了搜索算法优化，引入向量检索做混合召回，今天把方案分享出来。

## 一、传统 BM25 的问题

1. **同义词不匹配**：搜"前端开发"，"Vue工程师"、"React开发"、"web前端"搜不到
2. **语义不匹配**：搜"钱多事少"，"高薪轻松"的职位搜不到
3. **拼写错误**：搜"Java开发"打成"java开法"，搜不到结果
4. **排序单一**：只按相关性排序，没考虑职位质量、企业信誉、用户偏好

## 二、混合召回架构

```
用户查询 → 查询理解（纠错/同义词扩展/意图识别）
              ↓
        ┌─────┴─────┐
        ↓           ↓
    BM25 召回    向量召回
    （关键词）   （语义）
        ↓           ↓
        └─────┬─────┘
              ↓
         融合去重（Reciprocal Rank Fusion）
              ↓
         重排序（LTR 学习排序）
              ↓
         最终结果
```

## 三、向量检索实现

### 向量化

用 BGE 或 text-embedding 模型把职位标题和描述转成向量：

```python
from sentence_transformers import SentenceTransformer

model = SentenceTransformer('BAAI/bge-large-zh-v1.5')

# 职位向量化
job_text = f"{job['title']} {job['description']} {job['skills']}"
job_vector = model.encode(job_text)

# 存入 Elasticsearch（dense_vector 类型）
es.index(index="jobs_vector", id=job['id'], body={
    "vector": job_vector.tolist(),
    "job_id": job['id'],
})
```

### 向量搜索

```python
def vector_search(query, top_k=50):
    query_vector = model.encode(query)
    result = es.search(index="jobs_vector", body={
        "knn": {
            "field": "vector",
            "query_vector": query_vector.tolist(),
            "k": top_k,
            "num_candidates": 100,
        }
    })
    return [(hit["_source"]["job_id"], hit["_score"]) for hit in result["hits"]["hits"]]
```

### BM25 搜索

```python
def bm25_search(query, filters, top_k=50):
    result = es.search(index="jobs", body={
        "query": {
            "bool": {
                "must": [
                    {"multi_match": {
                        "query": query,
                        "fields": ["title^3", "skills^2", "description"],
                        "type": "best_fields"
                    }}
                ],
                "filter": filters
            }
        },
        "size": top_k
    })
    return [(hit["_id"], hit["_score"]) for hit in result["hits"]["hits"]]
```

## 四、融合与重排序

### RRF 融合

用 Reciprocal Rank Fusion 融合两路召回结果：

```python
def rrf_fuse(bm25_results, vector_results, k=60):
    scores = {}
    # BM25 路
    for rank, (doc_id, _) in enumerate(bm25_results):
        scores[doc_id] = scores.get(doc_id, 0) + 1 / (k + rank + 1)
    # 向量路
    for rank, (doc_id, _) in enumerate(vector_results):
        scores[doc_id] = scores.get(doc_id, 0) + 1 / (k + rank + 1)
    # 按融合分数排序
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)
```

### 重排序

融合后取 Top 100 用 LTR（Learning to Rank）模型重排序，考虑更多特征：

```python
def rerank(doc_ids, user_profile, query):
    features = []
    for doc_id in doc_ids:
        job = get_job(doc_id)
        features.append({
            "bm25_score": get_bm25_score(query, doc_id),
            "vector_score": get_vector_score(query, doc_id),
            "job_quality": job["quality_score"],       # 职位质量分
            "company_reputation": job["company_score"], # 企业信誉分
            "user_match": match_score(user_profile, job), # 用户匹配度
            "freshness": (time.time() - job["created_at"]) / 86400, # 新鲜度
            "click_rate": job["click_rate"],           # 历史点击率
        })

    # LTR 模型预测最终分数
    scores = ltr_model.predict(features)
    ranked = sorted(zip(doc_ids, scores), key=lambda x: x[1], reverse=True)
    return [doc_id for doc_id, _ in ranked]
```

## 五、查询理解

搜索前先做查询理解，提升召回质量：

```python
def query_understanding(query):
    # 1. 拼写纠错
    corrected = spell_check(query)

    # 2. 同义词扩展
    expanded = synonym_expand(corrected)  # "前端开发" → "前端开发 OR Vue OR React OR web前端"

    # 3. 意图识别
    intent = classify_intent(corrected)  # 找工作 / 查薪资 / 看公司

    # 4. 实体抽取
    entities = extract_entities(corrected)  # 城市、薪资、经验等过滤条件

    return {
        "original": query,
        "corrected": corrected,
        "expanded": expanded,
        "intent": intent,
        "entities": entities,
    }
```

## 六、效果

| 指标 | 优化前（BM25） | 优化后（混合召回） | 提升 |
|------|----------------|-------------------|------|
| 搜索点击率 | 12% | 16.2% | +35% |
| 零结果率 | 8% | 3% | -62% |
| 搜索后投递率 | 5% | 7.5% | +50% |
| 用户满意度 | 7.2/10 | 8.5/10 | +18% |

## 七、踩坑经验

1. **向量维度高存储大**：1024维向量，500万职位占 20GB+。用维度压缩（PCA降到512维）或乘积量化（PQ），损失少量精度换存储空间
2. **向量更新延迟**：职位更新后向量要重新生成，有秒级延迟。用异步队列更新，不影响主流程
3. **模型选择**：中文搜索用 BGE 或 text-embedding，不要用英文模型。选模型前先在自己的数据集上做评测
4. **召回量平衡**：BM25 和向量各召回 50 条，融合后取 100 条重排序。召回太少会漏，太多重排序性能差

## 八、总结

职位搜索混合召回核心：

1. **查询理解**：纠错、同义词扩展、意图识别、实体抽取，提升查询质量
2. **多路召回**：BM25 关键词召回 + 向量语义召回，兼顾精确匹配和语义匹配
3. **RRF 融合**：倒数排名融合，简单有效，不需要调参
4. **LTR 重排序**：融合后用学习排序模型重排，考虑职位质量、企业信誉、用户偏好等更多特征
5. **持续迭代**：搜索效果用 A/B 测试验证，根据用户点击反馈持续优化模型

搜索优化是个持续的过程，没有"最好"只有"更好"。混合召回是当前的主流方案，BM25 保证精确匹配，向量保证语义匹配，两者互补。后续还可以引入用户画像做个性化排序、用大模型做查询理解和结果摘要，搜索体验还有很大的提升空间。
