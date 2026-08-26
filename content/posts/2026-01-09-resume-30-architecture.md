---
title: "简历3.0改版架构：多端简历数据模型统一与接口协同设计"
date: 2026-01-09T10:00:00+08:00
draft: false
tags: ["架构设计", "数据模型", "Go", "微服务", "多端协同"]
categories: ["架构设计"]
summary: "简历3.0改版的架构设计，统一 PC/H5/小程序/App 四端简历数据模型，实现多端编辑协同、版本管理、增量同步，解决旧版数据不一致、接口不统一的问题。"
---

简历3.0改版是2026年初的重点项目，目标是统一 PC、H5、微信小程序、App 四端的简历数据模型，实现多端编辑协同。旧版四端各有各的数据结构和接口，数据不一致、维护困难。今天把改版架构分享出来。

## 一、旧版问题

1. **数据模型不统一**：PC 端简历字段多，小程序端字段少，同一份简历在不同端显示不一样
2. **接口不统一**：四端各有各的 API，同样的功能要写四遍
3. **编辑冲突**：用户在 PC 编辑了一半，又在小程序打开，数据覆盖
4. **没有版本管理**：简历修改后无法回退到历史版本
5. **同步延迟**：一端编辑后，另一端要刷新才能看到最新数据

## 二、统一数据模型

用 JSON 存储简历内容，支持灵活扩展：

```sql
CREATE TABLE `resume` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `user_id` bigint(20) NOT NULL,
  `version` int(11) NOT NULL DEFAULT '1' COMMENT '当前版本号',
  `content` json NOT NULL COMMENT '简历内容（统一JSON结构）',
  `status` tinyint(1) NOT NULL DEFAULT '1',
  `created_at` int(11) NOT NULL,
  `updated_at` int(11) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `user_id` (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

统一的 JSON 结构：

```json
{
  "basic_info": {
    "name": "张三",
    "phone": "138****1234",
    "email": "zhangsan@example.com",
    "avatar": "https://...",
    "gender": 1,
    "birthday": "1990-01-01",
    "city_id": 2
  },
  "job_intention": {
    "position": "Go开发工程师",
    "salary_min": 20000,
    "salary_max": 35000,
    "city_ids": [2, 1],
    "status": 1
  },
  "work_experiences": [
    {
      "id": "w1",
      "company": "某科技公司",
      "position": "高级工程师",
      "start_date": "2020-01",
      "end_date": "至今",
      "description": "负责...",
      "achievements": ["提升性能50%", "主导微服务重构"]
    }
  ],
  "educations": [...],
  "projects": [...],
  "skills": ["Go", "PHP", "MySQL", "Redis", "K8s"],
  "certificates": [...],
  "self_evaluation": "5年Go开发经验..."
}
```

所有端共用这一套 JSON 结构，不同端可以选择性显示字段，但数据是统一的。

## 三、多端编辑协同

### 乐观锁 + 版本号

用版本号防止编辑冲突：

```go
func (s *ResumeService) Update(userID int64, content map[string]interface{}, version int) error {
    // 1. 查当前版本
    resume := s.repo.GetByUserID(userID)

    // 2. 版本号校验（乐观锁）
    if resume.Version != version {
        return errors.New("简历已被其他端修改，请刷新后重试")
    }

    // 3. 更新内容，版本号+1
    resume.Content = content
    resume.Version++
    s.repo.Update(resume)

    // 4. 存历史版本
    s.versionRepo.Save(&ResumeVersion{
        ResumeID: resume.ID,
        Version: resume.Version,
        Content: content,
        CreatedAt: time.Now(),
    })

    // 5. 通知其他端刷新（WebSocket）
    s.websocket.BroadcastToUser(userID, "resume_updated", map[string]interface{}{
        "version": resume.Version,
    })

    return nil
}
```

### 增量同步

大简历全量传输慢，用增量同步，只传修改的字段：

```go
// 增量更新：只传修改的字段
func (s *ResumeService) Patch(userID int64, patch map[string]interface{}, version int) error {
    resume := s.repo.GetByUserID(userID)
    if resume.Version != version {
        return errors.New("版本冲突")
    }

    // 合并 patch 到 content（只更新指定字段）
    for key, value := range patch {
        resume.Content[key] = value
    }
    resume.Version++
    s.repo.Update(resume)
    return nil
}
```

前端调用时只传修改的字段，比如只改了工作经历，就只传 `work_experiences`，不传整个简历。

## 四、版本管理

每次修改都存历史版本，支持回退：

```sql
CREATE TABLE `resume_version` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `resume_id` bigint(20) NOT NULL,
  `version` int(11) NOT NULL,
  `content` json NOT NULL,
  `created_at` int(11) NOT NULL,
  PRIMARY KEY (`id`),
  KEY `resume_version` (`resume_id`,`version`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

```go
// 回退到指定版本
func (s *ResumeService) Rollback(userID int64, targetVersion int) error {
    resume := s.repo.GetByUserID(userID)
    target := s.versionRepo.Get(resume.ID, targetVersion)

    // 回退也是一次新版本
    resume.Content = target.Content
    resume.Version++
    s.repo.Update(resume)
    s.versionRepo.Save(&ResumeVersion{
        ResumeID: resume.ID,
        Version: resume.Version,
        Content: target.Content,
    })
    return nil
}
```

## 五、踩坑经验

1. **JSON 字段查询慢**：简历内容存在 JSON 字段，按技能、城市等条件查询时性能差。常用查询字段（城市、期望职位、工作年限）冗余到独立列，建索引
2. **大简历传输慢**：简历内容多时 JSON 体积大，全量更新慢。用增量同步（Patch），只传修改的字段
3. **多端冲突**：用户同时在两端编辑，乐观锁会拒绝后保存的一端。加了"合并冲突"提示，让用户选择保留哪端或手动合并
4. **版本存储膨胀**：每次修改都存全量版本，历史版本表增长快。只保留最近 20 个版本，更早的定期归档或删除

## 六、总结

简历3.0改版核心：

1. **统一数据模型**：四端共用一套 JSON 结构，数据一致，接口统一
2. **乐观锁防冲突**：版本号校验，防止多端编辑覆盖
3. **增量同步**：Patch 模式只传修改字段，减少传输量
4. **版本管理**：每次修改存历史版本，支持回退
5. **实时通知**：WebSocket 通知其他端刷新，多端数据实时同步
6. **查询优化**：常用字段冗余到独立列，解决 JSON 查询性能问题

多端协同的核心是"统一数据模型 + 版本控制 + 增量同步"。数据模型统一了，接口和展示才能统一；版本控制保证了多端编辑不冲突；增量同步提升了大内容的编辑体验。这三个点做好了，多端协同的基础就扎实了。
