---
title: "城市类目系统重构：从数据建模到接口校验的完整改造"
date: 2024-11-20T10:00:00+08:00
draft: false
tags: ["数据建模", "系统重构", "PHP", "Go", "接口设计"]
categories: ["架构设计"]
summary: "城市类目系统从旧版到新版的完整重构实践，涵盖数据模型设计、层级关系管理、接口校验、数据迁移，解决旧系统类目混乱、层级不清、维护困难的问题。"
---

招聘平台的城市类目系统最早是简单的两级结构（省→市），后来业务发展需要三级（省→市→区）、商圈、热门城市等多种维度，旧系统越来越难维护。2024年11月做了城市类目系统的重构，今天把完整改造过程分享出来。

## 一、旧系统问题

1. **层级混乱**：有的地方两级，有的地方三级，数据不一致
2. **字段冗余**：城市名、拼音、缩写、经纬度等字段散落在多张表
3. **维护困难**：加个商圈要改多张表，容易漏
4. **接口不统一**：不同业务线调用城市类目的接口不一样，返回格式不同
5. **没有版本管理**：城市类目变更没有记录，出问题查不到历史

## 二、新数据模型

用统一的树形结构，支持任意层级：

```sql
CREATE TABLE `region` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `parent_id` int(11) NOT NULL DEFAULT '0' COMMENT '父级ID，0为顶级',
  `level` tinyint(1) NOT NULL COMMENT '层级：1省 2市 3区 4商圈',
  `name` varchar(50) NOT NULL COMMENT '名称',
  `pinyin` varchar(100) DEFAULT NULL COMMENT '拼音',
  `pinyin_short` varchar(20) DEFAULT NULL COMMENT '拼音缩写',
  `longitude` decimal(10,6) DEFAULT NULL COMMENT '经度',
  `latitude` decimal(10,6) DEFAULT NULL COMMENT '纬度',
  `sort` int(11) NOT NULL DEFAULT '0' COMMENT '排序',
  `is_hot` tinyint(1) NOT NULL DEFAULT '0' COMMENT '是否热门',
  `status` tinyint(1) NOT NULL DEFAULT '1' COMMENT '1启用 0禁用',
  `created_at` int(11) NOT NULL,
  `updated_at` int(11) NOT NULL,
  PRIMARY KEY (`id`),
  KEY `parent_id` (`parent_id`),
  KEY `level_status` (`level`,`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

用 `parent_id` + `level` 表示层级关系，支持任意深度扩展。

## 三、接口设计

统一的 RESTful 接口：

```go
// 获取子级类目
GET /api/v1/regions?parent_id=1&level=2

// 获取完整树形结构
GET /api/v1/regions/tree

// 获取热门城市
GET /api/v1/regions/hot

// 搜索城市
GET /api/v1/regions/search?keyword=杭州

// 根据经纬度反查城市
GET /api/v1/regions/reverse?lng=120.15&lat=30.28
```

统一返回格式：

```json
{
  "code": 0,
  "data": [
    {"id": 1, "name": "浙江省", "level": 1, "children": [
      {"id": 2, "name": "杭州市", "level": 2, "children": [
        {"id": 3, "name": "西湖区", "level": 3}
      ]}
    ]}
  ]
}
```

## 四、接口校验

用 Go 的 validator 做参数校验：

```go
type RegionQuery struct {
    ParentID int    `form:"parent_id" binding:"omitempty,min=0"`
    Level    int    `form:"level" binding:"omitempty,oneof=1 2 3 4"`
    Keyword  string `form:"keyword" binding:"omitempty,max=50"`
}

func (h *RegionHandler) List(c *gin.Context) {
    var query RegionQuery
    if err := c.ShouldBindQuery(&query); err != nil {
        c.JSON(400, gin.H{"code": 1, "message": err.Error()})
        return
    }
    // ...
}
```

## 五、数据迁移

旧系统数据迁移到新表：

```go
func migrateRegions() error {
    // 1. 迁移省份
    provinces := queryOldProvinces()
    for _, p := range provinces {
        newID := createRegion(p.Name, 0, 1, p.Sort)
        // 记录映射关系
        setMapping("province", p.ID, newID)

        // 2. 迁移城市
        cities := queryOldCities(p.ID)
        for _, city := range cities {
            cityID := createRegion(city.Name, newID, 2, city.Sort)
            setMapping("city", city.ID, cityID)

            // 3. 迁移区县
            districts := queryOldDistricts(city.ID)
            for _, d := range districts {
                createRegion(d.Name, cityID, 3, d.Sort)
            }
        }
    }
    return nil
}
```

迁移完成后，业务表中的 city_id 要更新为新的 ID（用映射表）。

## 六、缓存策略

城市类目变更频率低，查询频率高，用 Redis 缓存：

```go
func (s *RegionService) GetTree() ([]*Region, error) {
    // 查缓存
    cached := s.redis.Get("region:tree").Val()
    if cached != "" {
        var tree []*Region
        json.Unmarshal([]byte(cached), &tree)
        return tree, nil
    }

    // 查数据库
    tree := s.repo.GetTree()
    data, _ := json.Marshal(tree)
    s.redis.Set("region:tree", data, 24*time.Hour)
    return tree, nil
}

// 类目变更时清缓存
func (s *RegionService) Update(id int, data *Region) error {
    err := s.repo.Update(id, data)
    if err == nil {
        s.redis.Del("region:tree") // 清缓存
    }
    return err
}
```

## 七、踩坑经验

1. **层级深度限制**：理论上支持任意层级，但实际查询时层级太深性能差。限制最多4级（省→市→区→商圈），够用且性能好
2. **城市重名**：不同省份有同名城市（如"朝阳区"北京和长春都有），查询时必须带 parent_id 或 level，不能只按 name 查
3. **经纬度精度**：旧系统经纬度精度不一致（有的6位小数，有的2位），迁移时统一格式化
4. **业务表关联更新**：城市类目 ID 变了，所有关联 city_id 的业务表都要更新。用映射表批量更新，遗漏会导致数据关联错误

## 八、总结

城市类目系统重构核心：

1. **统一数据模型**：树形结构支持任意层级，字段完整，消除冗余
2. **统一接口**：RESTful 风格，统一返回格式，所有业务线共用一套接口
3. **参数校验**：入参严格校验，防止非法数据
4. **数据迁移**：旧数据清洗后迁移，建立 ID 映射，业务表关联更新
5. **缓存优化**：变更低频查询高频，用 Redis 缓存，变更时主动清缓存
6. **版本管理**：类目变更记录日志，可追溯可回滚

基础数据系统的重构关键是"统一"——统一数据模型、统一接口、统一维护入口。旧系统的问题往往是因为不同业务线各自为政，数据模型和接口都不统一。重构时要把这些都收敛到一起，后续维护成本才能降下来。
