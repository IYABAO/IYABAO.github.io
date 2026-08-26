---
title: "招聘通分账号系统架构设计：多租户数据隔离与权限模型实践"
date: 2021-01-15T10:00:00+08:00
draft: false
tags: ["架构设计", "多租户", "权限模型", "PHP", "Yii2", "RBAC"]
categories: ["架构设计"]
summary: "招聘通分账号系统从0到1的架构设计，涵盖多租户数据隔离方案、RBAC 权限模型、子账号生命周期管理，以及实际落地中的踩坑经验。"
---

招聘通是我们平台的企业端招聘管理产品，最早是单账号模式——一个企业一个账号，所有人共用。随着客户规模变大，企业要求支持多账号、分权限管理：HR 专员只能看自己负责的职位，HR 经理能看全部，管理员能配置权限。2021年初我们做了分账号系统，今天把架构设计和落地经验分享出来。

## 一、需求分析

核心需求：

1. **多账号**：一个企业可以创建多个子账号，每个子账号独立登录
2. **角色权限**：预设角色（管理员、HR经理、HR专员、面试官），也支持自定义角色
3. **数据隔离**：子账号只能看到有权限的数据（职位、简历、面试等）
4. **操作审计**：记录子账号的关键操作，支持审计追溯
5. **账号生命周期**：创建、启用、禁用、删除，离职员工账号及时回收

## 二、数据隔离方案选型

多租户数据隔离有三种常见方案：

| 方案 | 隔离程度 | 成本 | 适用场景 |
|------|---------|------|---------|
| 独立数据库 | 最高 | 高 | 大客户、对数据隔离要求极高 |
| 共享数据库独立 Schema | 中 | 中 | 中等规模租户 |
| 共享数据库共享表（tenant_id） | 低 | 低 | 大量小租户 |

我们的场景是企业内部多账号，不是真正的多租户 SaaS，数据隔离要求没那么高。选了最简单的**共享表 + 企业ID隔离**方案，所有表带 `company_id` 字段，查询时自动加上企业过滤。

子账号级别的数据隔离（比如 HR 专员只能看自己的简历）通过权限系统在应用层控制，不是数据库层面隔离。

## 三、数据库设计

### 3.1 核心表结构

```sql
-- 企业表（已有，这里只列相关字段）
CREATE TABLE `company` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `name` varchar(100) NOT NULL,
  `status` tinyint(1) NOT NULL DEFAULT '1',
  `created_at` int(11) NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 账号表
CREATE TABLE `account` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `company_id` int(11) NOT NULL COMMENT '企业ID',
  `username` varchar(50) NOT NULL COMMENT '登录用户名',
  `password_hash` varchar(255) NOT NULL,
  `real_name` varchar(50) NOT NULL COMMENT '真实姓名',
  `email` varchar(100) DEFAULT NULL,
  `phone` varchar(20) DEFAULT NULL,
  `status` tinyint(1) NOT NULL DEFAULT '1' COMMENT '1正常 0禁用',
  `is_owner` tinyint(1) NOT NULL DEFAULT '0' COMMENT '是否企业主账号',
  `last_login_at` int(11) DEFAULT NULL,
  `last_login_ip` varchar(50) DEFAULT NULL,
  `created_at` int(11) NOT NULL,
  `updated_at` int(11) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `company_username` (`company_id`,`username`),
  KEY `company_id` (`company_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 角色表
CREATE TABLE `role` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `company_id` int(11) NOT NULL,
  `name` varchar(50) NOT NULL COMMENT '角色名称',
  `description` varchar(255) DEFAULT NULL,
  `is_system` tinyint(1) NOT NULL DEFAULT '0' COMMENT '是否系统预设角色（不可删除）',
  `created_at` int(11) NOT NULL,
  PRIMARY KEY (`id`),
  KEY `company_id` (`company_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 权限节点表
CREATE TABLE `permission` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `code` varchar(100) NOT NULL COMMENT '权限编码，如 job:view, job:edit',
  `name` varchar(50) NOT NULL COMMENT '权限名称',
  `module` varchar(50) NOT NULL COMMENT '所属模块',
  `parent_id` int(11) NOT NULL DEFAULT '0',
  `sort` int(11) NOT NULL DEFAULT '0',
  PRIMARY KEY (`id`),
  UNIQUE KEY `code` (`code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 角色权限关联表
CREATE TABLE `role_permission` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `role_id` int(11) NOT NULL,
  `permission_code` varchar(100) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `role_permission` (`role_id`,`permission_code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 账号角色关联表
CREATE TABLE `account_role` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `account_id` int(11) NOT NULL,
  `role_id` int(11) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `account_role` (`account_id`,`role_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 数据范围表（控制账号能看到哪些数据）
CREATE TABLE `account_data_scope` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `account_id` int(11) NOT NULL,
  `scope_type` varchar(20) NOT NULL COMMENT 'all:全部 dept:部门 self:自己',
  `dept_ids` varchar(500) DEFAULT NULL COMMENT '部门ID列表，scope_type=dept时有效',
  PRIMARY KEY (`id`),
  UNIQUE KEY `account_id` (`account_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

### 3.2 权限节点设计

权限用编码标识，按模块分层：

```
job:view          查看职位
job:create        创建职位
job:edit          编辑职位
job:delete        删除职位
job:refresh       刷新职位
resume:view       查看简历
resume:download   下载简历
resume:favorite   收藏简历
interview:create  创建面试
interview:edit    编辑面试
interview:cancel  取消面试
account:manage    账号管理
role:manage       角色管理
```

权限节点存在数据库里，系统初始化时导入。新增权限节点时通过数据库迁移添加。

## 四、权限校验实现

### 4.1 登录态与企业隔离

用户登录后，Session 里保存 account_id 和 company_id。所有查询自动加上 company_id 过滤，确保跨企业数据隔离。

用 Yii2 的 Behavior 实现自动加企业过滤：

```php
class CompanyScopeBehavior extends Behavior
{
    public function events()
    {
        return [
            ActiveRecord::EVENT_BEFORE_FIND => 'beforeFind',
            ActiveRecord::EVENT_BEFORE_INSERT => 'beforeInsert',
        ];
    }

    public function beforeFind($event)
    {
        $query = $event->sender;
        if (!Yii::$app->user->isGuest) {
            $companyId = Yii::$app->user->identity->company_id;
            $query->andWhere(['company_id' => $companyId]);
        }
    }

    public function beforeInsert($event)
    {
        $model = $event->sender;
        if (!Yii::$app->user->isGuest) {
            $model->company_id = Yii::$app->user->identity->company_id;
        }
    }
}
```

模型里挂上这个 Behavior，查询和插入时自动处理 company_id，业务代码不用关心。

### 4.2 权限校验中间件

用 Yii2 的 ActionFilter 做权限校验：

```php
class PermissionFilter extends ActionFilter
{
    public function beforeAction($action)
    {
        if (Yii::$app->user->isGuest) {
            throw new UnauthorizedHttpException('请先登录');
        }

        $account = Yii::$app->user->identity;
        
        // 主账号拥有所有权限
        if ($account->is_owner) {
            return true;
        }

        // 获取当前操作的权限编码
        $permissionCode = $this->getPermissionCode($action);
        if (!$permissionCode) {
            return true; // 不需要权限的接口放行
        }

        // 检查权限
        if (!Yii::$app->permission->check($account->id, $permissionCode)) {
            throw new ForbiddenHttpException('没有权限执行此操作');
        }

        return true;
    }

    private function getPermissionCode($action)
    {
        // 通过注解或配置映射 action 到 permission_code
        $map = [
            'job/index' => 'job:view',
            'job/create' => 'job:create',
            'job/update' => 'job:edit',
            'job/delete' => 'job:delete',
            'resume/index' => 'resume:view',
            'resume/download' => 'resume:download',
            // ...
        ];
        $route = $action->controller->id . '/' . $action->id;
        return $map[$route] ?? null;
    }
}
```

### 4.3 权限服务

权限检查用 Redis 缓存，避免每次查数据库：

```php
class PermissionService
{
    private $redis;

    public function __construct()
    {
        $this->redis = Yii::$app->redis;
    }

    public function check($accountId, $permissionCode)
    {
        $permissions = $this->getAccountPermissions($accountId);
        return in_array($permissionCode, $permissions);
    }

    public function getAccountPermissions($accountId)
    {
        $cacheKey = "perm:account:{$accountId}";
        $cached = $this->redis->get($cacheKey);
        if ($cached !== false) {
            return json_decode($cached, true);
        }

        // 查数据库：账号 → 角色 → 权限
        $permissions = (new Query())
            ->select('rp.permission_code')
            ->from('account_role ar')
            ->leftJoin('role_permission rp', 'ar.role_id = rp.role_id')
            ->where(['ar.account_id' => $accountId])
            ->column();

        $this->redis->setex($cacheKey, 3600, json_encode($permissions));
        return $permissions;
    }

    public function clearCache($accountId)
    {
        $this->redis->del("perm:account:{$accountId}");
    }
}
```

角色或账号权限变更时，调用 `clearCache()` 清缓存。

### 4.4 数据范围控制

数据范围控制账号能看到哪些数据。比如 HR 专员只能看到自己创建的职位，HR 经理能看到全公司的。

```php
class DataScopeService
{
    public function applyJobScope($query, $accountId)
    {
        $scope = AccountDataScope::findOne(['account_id' => $accountId]);
        if (!$scope) {
            return $query; // 没有配置数据范围，默认看全部
        }

        switch ($scope->scope_type) {
            case 'self':
                // 只看自己创建的
                $query->andWhere(['created_by' => $accountId]);
                break;
            case 'dept':
                // 看指定部门的
                $deptIds = explode(',', $scope->dept_ids);
                $accountIds = Account::find()
                    ->select('id')
                    ->where(['dept_id' => $deptIds])
                    ->column();
                $query->andWhere(['created_by' => $accountIds]);
                break;
            case 'all':
            default:
                // 看全部，不加条件
                break;
        }

        return $query;
    }
}
```

## 五、操作审计

关键操作记录审计日志：

```sql
CREATE TABLE `audit_log` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `company_id` int(11) NOT NULL,
  `account_id` int(11) NOT NULL,
  `account_name` varchar(50) NOT NULL,
  `action` varchar(50) NOT NULL COMMENT '操作类型',
  `target_type` varchar(50) DEFAULT NULL COMMENT '操作对象类型',
  `target_id` int(11) DEFAULT NULL COMMENT '操作对象ID',
  `detail` text COMMENT '操作详情（JSON）',
  `ip` varchar(50) DEFAULT NULL,
  `user_agent` varchar(500) DEFAULT NULL,
  `created_at` int(11) NOT NULL,
  PRIMARY KEY (`id`),
  KEY `company_id` (`company_id`),
  KEY `account_id` (`account_id`),
  KEY `created_at` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

用 Behavior 自动记录审计日志：

```php
class AuditBehavior extends Behavior
{
    public function events()
    {
        return [
            ActiveRecord::EVENT_AFTER_INSERT => 'afterInsert',
            ActiveRecord::EVENT_AFTER_UPDATE => 'afterUpdate',
            ActiveRecord::EVENT_AFTER_DELETE => 'afterDelete',
        ];
    }

    public function afterInsert($event)
    {
        $this->log('create', $event->sender);
    }

    public function afterUpdate($event)
    {
        $this->log('update', $event->sender);
    }

    public function afterDelete($event)
    {
        $this->log('delete', $event->sender);
    }

    private function log($action, $model)
    {
        if (Yii::$app->user->isGuest) return;

        $log = new AuditLog();
        $log->company_id = Yii::$app->user->identity->company_id;
        $log->account_id = Yii::$app->user->identity->id;
        $log->account_name = Yii::$app->user->identity->real_name;
        $log->action = $action;
        $log->target_type = get_class($model);
        $log->target_id = $model->primaryKey;
        $log->detail = json_encode($model->attributes, JSON_UNESCAPED_UNICODE);
        $log->ip = Yii::$app->request->userIP;
        $log->user_agent = Yii::$app->request->userAgent;
        $log->created_at = time();
        $log->save();
    }
}
```

## 六、踩过的坑

**1. 权限缓存不一致**

角色权限变更后只清了角色关联的账号缓存，漏了一些账号，导致权限变更后部分账号还是旧权限。后来改成角色变更时，查所有关联这个角色的账号，全部清缓存。

**2. 企业隔离 Behavior 漏掉关联查询**

CompanyScopeBehavior 只处理了主表查询，关联查询（JOIN）时没加企业过滤，导致跨企业数据泄露。后来在所有关联查询里手动加了企业条件，或者用子查询替代 JOIN。

**3. 主账号权限绕过**

主账号（is_owner=1）应该拥有所有权限，但有些地方直接查角色权限表，主账号没关联角色，返回空权限。在权限服务里加了主账号短路判断，主账号直接返回 true。

**4. 数据范围与权限的关系没理清**

数据范围和功能权限是两个维度：功能权限控制能不能操作（如能不能删除职位），数据范围控制能看到哪些数据（如能看到哪些职位）。一开始混在一起，后来拆成两个独立的服务，逻辑清晰了很多。

**5. 审计日志表膨胀**

审计日志增长很快，一年就到了几千万条，查询变慢。后来按月份分区，超过一年的日志归档到冷存储，只保留近一年的在线查询。

## 七、总结

分账号系统的核心设计：

1. **数据隔离**：共享表 + company_id，Behavior 自动加过滤，业务代码无感知
2. **权限模型**：RBAC（账号 → 角色 → 权限），支持预设角色和自定义角色
3. **数据范围**：独立于功能权限，控制能看到的数据范围（全部/部门/自己）
4. **权限缓存**：Redis 缓存权限，变更时主动清缓存
5. **操作审计**：Behavior 自动记录关键操作，支持审计追溯
6. **账号生命周期**：创建/启用/禁用/删除，离职及时回收权限

这套系统上线后，支撑了几千家企业的多账号管理，稳定性和性能都没问题。架构上留了扩展空间，后续加了部门管理、审批流程等功能，都是在这个基础上扩展的。

多账号系统的设计难点不在技术，而在业务逻辑的梳理——权限和数据范围的边界要划清楚，否则很容易出现越权或数据泄露。设计阶段多花时间梳理需求，比上线后补漏洞成本低得多。
