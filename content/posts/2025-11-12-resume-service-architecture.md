---
title: "新版简历服务架构：Go 微服务分层设计与缓存一致性保障"
date: 2025-11-12T10:00:00+08:00
draft: false
tags: ["Go", "微服务", "分层架构", "缓存", "一致性", "gRPC"]
categories: ["Go开发"]
summary: "新版简历服务的 Go 微服务架构设计，涵盖分层架构、gRPC 接口、多级缓存、缓存一致性保障、读写分离，支撑千万级简历的高并发查询和更新。"
---

简历服务是招聘平台的核心服务，支撑简历的创建、编辑、搜索、查看、投递等功能。旧版是 PHP 单体，性能和扩展性都不够。2025年11月做了新版 Go 微服务重构，今天把架构设计分享出来。

## 一、分层架构

```
API 层（HTTP/gRPC）→ Handler 层 → Service 层 → Repository 层 → 数据库/缓存
```

### Handler 层

处理请求参数校验、鉴权、响应格式化，不包含业务逻辑：

```go
type ResumeHandler struct {
    service *ResumeService
}

func (h *ResumeHandler) Get(c *gin.Context) {
    id, _ := strconv.ParseInt(c.Param("id"), 10, 64)
    userID := c.GetInt64("user_id")

    // 参数校验
    if id <= 0 {
        c.JSON(400, gin.H{"code": 1, "message": "无效的简历ID"})
        return
    }

    // 调用 Service 层
    resume, err := h.service.Get(id, userID)
    if err != nil {
        c.JSON(500, gin.H{"code": 500, "message": err.Error()})
        return
    }

    c.JSON(200, gin.H{"code": 0, "data": resume})
}
```

### Service 层

业务逻辑层，处理业务规则、事务、缓存：

```go
type ResumeService struct {
    repo *ResumeRepository
    cache *ResumeCache
    eventBus *EventBus
}

func (s *ResumeService) Get(id int64, userID int64) (*Resume, error) {
    // 1. 查缓存
    resume, err := s.cache.Get(id)
    if err == nil {
        return resume, nil
    }

    // 2. 缓存未命中，查数据库
    resume, err = s.repo.GetByID(id)
    if err != nil {
        return nil, err
    }

    // 3. 权限校验
    if !s.canView(resume, userID) {
        return nil, errors.New("无权限查看")
    }

    // 4. 回写缓存
    s.cache.Set(resume)

    return resume, nil
}

func (s *ResumeService) Update(resume *Resume) error {
    // 1. 数据库事务更新
    err := s.repo.Update(resume)
    if err != nil {
        return err
    }

    // 2. 失效缓存（不是更新，是删除）
    s.cache.Delete(resume.ID)

    // 3. 发事件（异步通知搜索服务更新索引）
    s.eventBus.Publish("resume.updated", resume)

    return nil
}
```

### Repository 层

数据访问层，封装数据库和缓存操作：

```go
type ResumeRepository struct {
    db *gorm.DB
}

func (r *ResumeRepository) GetByID(id int64) (*Resume, error) {
    var resume Resume
    err := r.db.First(&resume, id).Error
    return &resume, err
}

func (r *ResumeRepository) Update(resume *Resume) error {
    return r.db.Save(resume).Error
}

func (r *ResumeRepository) Search(query *SearchQuery) ([]*Resume, int64, error) {
    // 复杂查询，多条件筛选
    db := r.db.Model(&Resume{})
    if query.Keyword != "" {
        db = db.Where("title LIKE ?", "%"+query.Keyword+"%")
    }
    if query.CityID > 0 {
        db = db.Where("city_id = ?", query.CityID)
    }
    // ... 更多条件

    var total int64
    db.Count(&total)

    var resumes []*Resume
    db.Offset((query.Page-1)*query.PageSize).Limit(query.PageSize).Find(&resumes)
    return resumes, total, nil
}
```

## 二、多级缓存

```
本地缓存（APCu/FreeCache）→ Redis 集群 → MySQL
```

```go
type ResumeCache struct {
    local *freecache.Cache  // 本地缓存，1分钟
    redis *redis.Client     // Redis 缓存，10分钟
}

func (c *ResumeCache) Get(id int64) (*Resume, error) {
    // 1. 先查本地缓存
    key := []byte(fmt.Sprintf("resume:%d", id))
    if data, err := c.local.Get(key); err == nil {
        var resume Resume
        json.Unmarshal(data, &resume)
        return &resume, nil
    }

    // 2. 再查 Redis
    data, err := c.redis.Get(context.Background(), string(key)).Bytes()
    if err == nil {
        var resume Resume
        json.Unmarshal(data, &resume)
        // 回写本地缓存
        c.local.Set(key, data, 60)
        return &resume, nil
    }

    return nil, errors.New("cache miss")
}

func (c *ResumeCache) Delete(id int64) {
    key := fmt.Sprintf("resume:%d", id)
    c.local.Del([]byte(key))
    c.redis.Del(context.Background(), key)
}
```

## 三、缓存一致性

缓存一致性是难点，用 Cache-Aside 模式 + 延迟双删：

```go
func (s *ResumeService) Update(resume *Resume) error {
    // 1. 先删缓存
    s.cache.Delete(resume.ID)

    // 2. 更新数据库
    err := s.repo.Update(resume)
    if err != nil {
        return err
    }

    // 3. 延迟再删缓存（防止并发读回写旧数据）
    go func() {
        time.Sleep(500 * time.Millisecond)
        s.cache.Delete(resume.ID)
    }()

    return nil
}
```

延迟双删解决"读请求在更新数据库前查了旧数据，更新后回写缓存"的竞态问题。

## 四、读写分离

查询走从库，写入走主库：

```go
type ResumeRepository struct {
    master *gorm.DB
    slaves []*gorm.DB
}

func (r *ResumeRepository) GetByID(id int64) (*Resume, error) {
    // 读走从库（轮询）
    db := r.slaves[rand.Intn(len(r.slaves))]
    var resume Resume
    err := db.First(&resume, id).Error
    return &resume, err
}

func (r *ResumeRepository) Update(resume *Resume) error {
    // 写走主库
    return r.master.Save(resume).Error
}
```

## 五、踩坑经验

1. **缓存击穿**：热点简历缓存过期瞬间，大量请求打到数据库。加互斥锁（SETNX），只有一个请求查数据库，其他等待缓存
2. **缓存穿透**：查询不存在的简历，每次都查数据库。缓存空值（短过期时间），或用布隆过滤器过滤不存在的 ID
3. **主从延迟**：刚更新简历后立即查询，从库还没同步，看到旧数据。关键查询走主库，或加"读写一致"标记
4. **大字段缓存**：简历包含工作经历、教育经历等，JSON 大，缓存占内存。大字段单独缓存，列表查询只缓存摘要

## 六、总结

新版简历服务架构核心：

1. **分层架构**：Handler/Service/Repository 三层分离，职责清晰，易于测试和维护
2. **多级缓存**：本地缓存 + Redis + 数据库，层层拦截，提升查询性能
3. **缓存一致性**：Cache-Aside + 延迟双删，保证缓存和数据库最终一致
4. **读写分离**：查询走从库，写入走主库，提升并发能力
5. **事件驱动**：简历更新发事件，搜索服务异步更新索引，解耦
6. **高可用**：缓存击穿/穿透/雪崩都有应对方案，保证稳定性

微服务重构的核心不是"用 Go 重写"，而是"分层解耦 + 缓存优化 + 高可用设计"。Go 的性能优势只是其中一部分，架构设计才是决定系统能扛多大流量的关键。
