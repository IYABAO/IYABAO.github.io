---
title: "RAG 检索增强生成实战：从文档切分到向量检索完整方案"
date: 2025-01-15T10:00:00+08:00
draft: false
tags: ["RAG", "大模型", "向量检索", "AI应用", "LangChain", "知识库"]
categories: ["AI架构"]
summary: "RAG（检索增强生成）的完整落地方案，涵盖文档切分策略、向量化、向量检索、重排序、Prompt 工程，以及在招聘场景下的实际应用和踩坑经验。"
---

大模型有知识截止日期，而且不知道企业内部数据。RAG（Retrieval-Augmented Generation，检索增强生成）是解决这个问题的主流方案——先从知识库检索相关文档，再把文档作为上下文传给大模型生成回答。2025年初我们在招聘平台做了 RAG 知识库，让 AI 能基于公司制度、岗位说明、历史简历等内部数据回答问题。今天把完整方案分享出来。

## 一、RAG 整体流程

```
用户提问 → 查询理解 → 向量检索 → 重排序 → 上下文构建 → Prompt 组装 → 大模型生成 → 回答
                ↑
           文档处理（离线）：
           文档加载 → 文档切分 → 向量化 → 存入向量数据库
```

分为两个阶段：
1. **离线索引阶段**：文档加载、切分、向量化、存入向量数据库
2. **在线检索阶段**：查询理解、检索、重排序、上下文构建、大模型生成

## 二、文档处理

### 文档加载

支持多种格式：PDF、Word、Markdown、HTML、纯文本。用 LangChain 的 document loader：

```python
from langchain_community.document_loaders import (
    PyPDFLoader, Docx2txtLoader, TextLoader, UnstructuredHTMLLoader
)

def load_document(file_path: str):
    ext = file_path.split('.')[-1].lower()
    loaders = {
        'pdf': PyPDFLoader,
        'docx': Docx2txtLoader,
        'doc': Docx2txtLoader,
        'txt': TextLoader,
        'md': TextLoader,
        'html': UnstructuredHTMLLoader,
    }
    loader_class = loaders.get(ext, TextLoader)
    loader = loader_class(file_path)
    return loader.load()
```

### 文档切分

切分是 RAG 最关键的步骤之一，切得太大检索不精准，切得太小丢失上下文。

```python
from langchain.text_splitter import RecursiveCharacterTextSplitter

text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=500,        # 每个 chunk 500 字符
    chunk_overlap=50,      # 相邻 chunk 重叠 50 字符，防止上下文断裂
    separators=["\n\n", "\n", "。", "！", "？", ".", " ", ""],  # 优先在段落、句子边界切分
)

chunks = text_splitter.split_documents(documents)
```

**切分策略要点**：
- **按语义边界切分**：优先在段落、标题、句子边界切，不要在句子中间切断
- **重叠保留上下文**：相邻 chunk 重叠 10%-20%，防止关键信息被切断
- **按文档类型调整**：制度文档 chunk 大一些（800-1000），FAQ 文档按问答对切，代码文档按函数切
- **保留元数据**：每个 chunk 带上文档名、页码、章节标题等元数据，检索后能溯源

### 向量化

用 Embedding 模型把文本转成向量：

```python
from langchain_community.embeddings import HuggingFaceBgeEmbeddings

# 用 BGE 中文 Embedding 模型，效果比 OpenAI 的在中文上好
embeddings = HuggingFaceBgeEmbeddings(
    model_name="BAAI/bge-large-zh-v1.5",
    model_kwargs={'device': 'cuda'},
    encode_kwargs={'normalize_embeddings': True},  # 归一化，方便余弦相似度
)

# 批量向量化
texts = [chunk.page_content for chunk in chunks]
vectors = embeddings.embed_documents(texts)
```

**Embedding 模型选型**：
- 中文场景：BGE-large-zh-v1.5（开源，效果好）、text-embedding-v3（通义千问）
- 英文场景：text-embedding-3-large（OpenAI）、Cohere embed-v3
- 部署方式：开源模型本地部署（成本低、数据不出域），API 模型调用（省事、按量付费）

## 三、向量存储

```python
from langchain_community.vectorstores import Milvus

# 存入 Milvus
vector_store = Milvus.from_documents(
    documents=chunks,
    embedding=embeddings,
    connection_args={"host": "milvus", "port": "19530"},
    collection_name="knowledge_base",
)

# 也可以用 pgvector（PostgreSQL 插件，不用单独维护向量数据库）
# from langchain_community.vectorstores import PGVector
# vector_store = PGVector.from_documents(...)
```

## 四、检索与重排序

### 基础检索

```python
def retrieve(query: str, top_k: int = 5):
    # 向量相似度检索
    docs = vector_store.similarity_search(query, k=top_k)
    return docs
```

### 查询优化

用户的问题可能不适合直接检索，先做查询理解和扩展：

```python
def query_understanding(query: str) -> str:
    """查询优化：提取关键词、扩展同义词、纠正错别字"""
    prompt = f"""
    你是一个搜索查询优化专家。请对以下用户问题进行优化，使其更适合向量检索。
    要求：
    1. 提取核心关键词
    2. 扩展相关同义词
    3. 去除无关词汇
    4. 输出优化后的查询语句，不要解释

    用户问题：{query}
    优化后查询：
    """
    optimized = llm.invoke(prompt).content
    return optimized
```

### 混合检索

向量检索 + 关键词检索（BM25）结合，效果更好：

```python
from langchain.retrievers import EnsembleRetriever
from langchain_community.retrievers import BM25Retriever

# BM25 关键词检索
bm25_retriever = BM25Retriever.from_documents(chunks)
bm25_retriever.k = 5

# 向量检索
vector_retriever = vector_store.as_retriever(search_kwargs={"k": 5})

# 混合检索（RRF 融合）
ensemble_retriever = EnsembleRetriever(
    retrievers=[bm25_retriever, vector_retriever],
    weights=[0.5, 0.5],
)

docs = ensemble_retriever.get_relevant_documents(query)
```

### 重排序（Rerank）

检索回来的 top_k 结果，用 Cross-Encoder 模型重新排序，提升精准度：

```python
from sentence_transformers import CrossEncoder

reranker = CrossEncoder('BAAI/bge-reranker-large')

def rerank(query: str, docs, top_n: int = 3):
    # 计算 query 和每个 doc 的相关性分数
    pairs = [(query, doc.page_content) for doc in docs]
    scores = reranker.predict(pairs)

    # 按分数排序，取 top_n
    scored_docs = list(zip(docs, scores))
    scored_docs.sort(key=lambda x: x[1], reverse=True)
    return [doc for doc, score in scored_docs[:top_n]]
```

重排序是 RAG 效果提升的关键——向量检索召回相关文档，重排序从相关文档里挑出最相关的几个，大幅减少无关上下文对大模型的干扰。

## 五、Prompt 组装

```python
def build_prompt(query: str, docs) -> str:
    # 把检索到的文档格式化成上下文
    context = "\n\n".join([
        f"【文档{i+1}】{doc.page_content}\n（来源：{doc.metadata.get('source', '未知')}）"
        for i, doc in enumerate(docs)
    ])

    prompt = f"""
    你是一个专业的招聘平台知识库助手。请根据以下参考文档回答用户的问题。

    【参考文档】
    {context}

    【用户问题】
    {query}

    【回答要求】
    1. 只根据参考文档回答，不要编造信息
    2. 如果参考文档里没有相关信息，回答"根据现有知识库无法回答该问题"
    3. 回答要简洁准确，引用文档时标注来源
    4. 用中文回答
    """
    return prompt
```

## 六、完整 RAG 流程

```python
def rag_answer(query: str) -> str:
    # 1. 查询优化
    optimized_query = query_understanding(query)

    # 2. 混合检索
    docs = ensemble_retriever.get_relevant_documents(optimized_query)

    # 3. 重排序
    relevant_docs = rerank(query, docs, top_n=3)

    # 4. 构建 Prompt
    prompt = build_prompt(query, relevant_docs)

    # 5. 大模型生成
    answer = llm.invoke(prompt).content

    return answer
```

## 七、在招聘场景的应用

我们做了几个 RAG 应用：

1. **制度问答**：公司人事制度、考勤制度、报销制度，员工问 AI 直接回答，不用查文档
2. **岗位说明问答**：每个岗位的职责、要求、晋升路径，求职者和面试官都能问
3. **简历智能解析辅助**：解析简历时检索岗位 JD，判断简历和岗位的匹配度
4. **面试问题推荐**：根据岗位 JD 检索相关面试问题，推荐给面试官

## 八、效果评估

RAG 效果怎么评估？不能只靠感觉，要有量化指标：

| 指标 | 说明 | 目标 |
|------|------|------|
| 召回率 | 相关文档是否被检索回来 | > 90% |
| 精准率 | 检索回来的文档是否相关 | > 70% |
| 回答准确率 | 大模型回答是否正确 | > 85% |
| 幻觉率 | 回答中编造信息的比例 | < 5% |
| 拒答率 | 无法回答的问题比例 | 合理范围 |

用标注好的问答对做测试集，自动评估。

## 九、踩坑经验

1. **文档切分是关键**：初期用固定大小切分，效果很差。改成按语义边界切分 + 重叠后，召回率提升 30%
2. **Embedding 模型要选对**：初期用 OpenAI 的 text-embedding-ada-002，中文效果不好。换成 BGE-large-zh 后，中文检索效果明显提升
3. **重排序不能省**：只做向量检索，top5 里经常有 2-3 个不相关的。加了 bge-reranker 重排序后，top3 基本都是相关的
4. **上下文窗口限制**：检索的文档太多，超过大模型上下文窗口。控制 top_n=3-5，每个 chunk 500 字，总上下文不超过 4000 token
5. **幻觉问题**：大模型有时不基于文档回答，自己编。在 Prompt 里强调"只根据参考文档回答，没有就说不知道"，加温度=0，能大幅减少幻觉
6. **文档更新延迟**：文档更新后，向量数据库里的旧 chunk 还在。文档更新时要先删旧的再插入新的，用文档 ID 做关联
7. **多语言问题**：知识库有中文文档也有英文文档，用户用中文问可能检索到英文文档。Embedding 模型选多语言版本，或者查询时做语言检测

## 十、总结

RAG 落地核心：

1. **文档切分是基础**：按语义边界切分 + 重叠 + 保留元数据，切分得好 RAG 就成功了一半
2. **Embedding 选对模型**：中文场景用 BGE，不要盲目用 OpenAI 的模型
3. **混合检索 + 重排序**：向量检索 + BM25 混合召回，Cross-Encoder 重排序，精准度大幅提升
4. **Prompt 工程**：明确告诉模型只根据文档回答，减少幻觉，标注来源
5. **效果量化评估**：用测试集自动评估召回率、准确率、幻觉率，持续优化
6. **迭代优化**：RAG 不是一次做好就完事，根据 bad case 持续优化切分策略、检索参数、Prompt

RAG 是目前让大模型使用私有数据最可靠的方案，比微调成本低、更新快、可溯源。但 RAG 不是"搭个向量数据库就行"，文档切分、检索策略、重排序、Prompt 工程每个环节都影响最终效果。建议从简单方案开始（单文档、固定切分、纯向量检索），跑通后再逐步加混合检索、重排序、查询优化，用 bad case 驱动优化。
