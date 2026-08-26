---
title: "用户中心架构演进：从单体到微服务的用户体系拆分实践"
date: 2024-02-26T10:00:00+08:00
draft: false
tags: ["微服务", "架构演进", "用户中心", "Go", "gRPC", "数据迁移"]
categories: ["架构设计"]
summary: "用户中心从单体应用拆分为独立微服务的架构演进实践，涵盖服务拆分策略、数据迁移方案、gRPC 接口设计、灰度切换流程，以及拆分过程中的踩坑经验。"
---

招聘平台的用户体系最早耦合在各个业务系统里——PC端、App端、小程序各有一套用户表，注册登录逻辑重复实现，数据不一致。2024年初做了用户中心的微服务拆分，把用户体系抽成独立服务。今天把拆分实践分享出来。

## 一、问题

1. **重复实现**：PC、App、小程序各有一套注册登录逻辑，维护成本高
2. **数据不一致**：三个端的用户表数据不同步，同一个用户在不同端信息不一样
3. **扩展困难**：加新的登录方式（如微信、手机号）要改三个端的代码
4. **安全风险**：密码加密方式不统一，有的用 md5，有的用 bcrypt

## 二、拆分策略

### 2.1 服务边界

用户中心负责：
- 用户注册、登录、登出
- 用户信息管理（基本资料、头像、密码）
- 第三方账号绑定（微信、QQ、微博）
- Token 管理（签发、刷新、吊销）
- 权限校验（用户状态、角色）

不负责：
- 企业信息（归企业中心）
- 求职者简历（归简历中心）
- 业务权限（归各业务系统）

### 2.2 技术选型

- 语言：Go（性能高，适合基础服务）
- 通信：gRPC（内部服务调用）+ HTTP（外部 API 网关）
- 数据库：MySQL（用户主数据）+ Redis（Token 缓存、限流）
- 注册发现：etcd

## 三、数据迁移

### 3.1 数据合并

三个端的用户表合并成一张，用手机号/邮箱做唯一标识去重：

```sql
-- 新用户表
CREATE TABLE `user` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `phone` varchar(20) DEFAULT NULL,
  `email` varchar(100) DEFAULT NULL,
  `password_hash` varchar(255) NOT NULL,
  `nickname` varchar(50) DEFAULT NULL,
  `avatar` varchar(255) DEFAULT NULL,
  `status` tinyint(1) NOT NULL DEFAULT '1',
  `created_at` int(11) NOT NULL,
  `updated_at` int(11) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `phone` (`phone`),
  UNIQUE KEY `email` (`email`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

### 3.2 迁移脚本

```go
func migrateUsers() error {
    // 1. 从三个端的旧表读取用户
    pcUsers := queryPCUsers()
    appUsers := queryAppUsers()
    mpUsers := queryMPUsers()

    // 2. 按手机号去重合并
    merged := mergeByPhone(pcUsers, appUsers, mpUsers)

    // 3. 密码统一加密（旧 md5 转 bcrypt）
    for _, user := range merged {
        if isMD5(user.PasswordHash) {
            // 标记需要首次登录时重置密码
            user.NeedResetPassword = true
        }
    }

    // 4. 批量写入新表
    return batchInsertUsers(merged)
}
```

### 3.3 双写过渡

迁移期间用双写保证数据一致：

```go
func (s *UserService) Register(req *RegisterRequest) (*User, error) {
    // 1. 写新用户中心
    user, err := s.createUser(req)
    if err != nil {
        return nil, err
    }

    // 2. 异步写旧系统（保证旧系统也能查到）
    s.queue.Publish(&OldSystemSyncMessage{
        UserID: user.ID,
        Data: req,
    })

    return user, nil
}
```

## 四、gRPC 接口设计

```protobuf
service UserService {
    rpc Register(RegisterRequest) returns (User);
    rpc Login(LoginRequest) returns (LoginResponse);
    rpc GetUser(GetUserRequest) returns (User);
    rpc UpdateUser(UpdateUserRequest) returns (User);
    rpc ChangePassword(ChangePasswordRequest) returns (Empty);
    rpc ValidateToken(ValidateTokenRequest) returns (ValidateTokenResponse);
}

message User {
    int64 id = 1;
    string phone = 2;
    string email = 3;
    string nickname = 4;
    string avatar = 5;
    int32 status = 6;
    int64 created_at = 7;
}
```

## 五、灰度切换

1. **第一阶段**：新用户中心上线，旧系统继续运行，双写数据
2. **第二阶段**：小程序端切到新用户中心，观察一周
3. **第三阶段**：App 端切换，观察一周
4. **第四阶段**：PC 端切换，全量切换完成
5. **第五阶段**：旧系统下线，清理旧代码和旧表

每个阶段都有回滚预案，出问题快速切回旧系统。

## 六、踩坑经验

1. **密码迁移**：旧系统用 md5 加密，新系统用 bcrypt，不能直接转换。方案：保留旧密码 hash，用户首次登录时验证旧密码后自动升级为 bcrypt
2. **用户 ID 映射**：旧系统三个端各有各的用户 ID，新系统统一 ID 后，旧业务数据里的 user_id 要做映射。用映射表记录 old_id → new_id
3. **Token 兼容**：切换期间新旧系统的 Token 要互相识别，旧 Token 在新系统也能验证通过（加兼容层）
4. **数据一致性**：双写期间可能出现新系统写成功但旧系统写失败的情况。用对账脚本每天校验，不一致的数据自动修复

## 七、总结

用户中心微服务拆分核心：

1. **明确边界**：用户中心只负责用户相关的核心能力，不掺杂业务逻辑
2. **数据先行**：先做数据合并和迁移，再做服务拆分
3. **双写过渡**：迁移期间双写保证数据一致，降低切换风险
4. **灰度切换**：按端逐步切换，每个阶段观察验证，有回滚预案
5. **兼容设计**：密码、Token、用户 ID 都要做兼容，不能让用户感知到切换
6. **统一标准**：拆分后统一密码加密、Token 格式、接口规范

微服务拆分不是"拆了就完事"，数据迁移、灰度切换、兼容设计才是最难的部分。用户中心是基础服务，稳定性要求极高，拆分过程一定要稳，不能影响用户体验。能用灰度和双写解决的问题，就不要冒险一次性切换。
