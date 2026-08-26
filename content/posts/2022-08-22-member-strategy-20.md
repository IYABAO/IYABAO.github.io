---
title: "普通会员策略 2.0：基于状态机的会员生命周期管理"
date: 2022-08-22T10:00:00+08:00
draft: false
tags: ["状态机", "会员系统", "PHP", "业务建模", "架构设计"]
categories: ["架构设计"]
summary: "普通会员策略 2.0 重构，基于状态机管理会员生命周期，解决 1.0 版本 if-else 嵌套、状态混乱的问题，实现会员状态流转的可配置、可追溯、可扩展。"
---

普通会员策略 1.0 版本用了大量 if-else 判断会员状态，代码里到处都是 `if ($member->status == 'active' && $member->expire_time > time())` 这样的判断，状态流转分散在各个业务方法里，加新状态要改很多地方。2022年8月做了 2.0 重构，用状态机管理会员生命周期，今天把设计思路分享出来。

## 一、1.0 的问题

1. **状态分散**：会员状态（待激活、正常、过期、冻结、注销）流转散落在各个方法里
2. **if-else 嵌套**：判断会员是否可用要检查状态、过期时间、冻结原因等多个条件
3. **不可追溯**：状态变更没有记录，出问题查不到什么时候、因为什么变的状态
4. **扩展困难**：加新状态（如暂停）要改所有判断逻辑，容易漏改
5. **并发问题**：状态变更没有原子保护，并发请求可能导致状态错乱

## 二、状态机设计

### 2.1 状态定义

```php
class MemberStatus
{
    const PENDING = 'pending';       // 待激活（注册未验证）
    const ACTIVE = 'active';         // 正常
    const EXPIRED = 'expired';       // 过期
    const FROZEN = 'frozen';         // 冻结（违规）
    const SUSPENDED = 'suspended';   // 暂停（用户主动）
    const CANCELLED = 'cancelled';   // 注销
}
```

### 2.2 状态流转图

```
待激活 → 正常 → 过期 → 正常（续费）
         ↓       ↓
       冻结    暂停
         ↓       ↓
       正常    正常
         ↓
       注销
```

### 2.3 流转规则配置

用配置定义允许的状态流转：

```php
class MemberStateMachine
{
    private $transitions = [
        MemberStatus::PENDING => [
            'activate' => MemberStatus::ACTIVE,
            'cancel' => MemberStatus::CANCELLED,
        ],
        MemberStatus::ACTIVE => [
            'expire' => MemberStatus::EXPIRED,
            'freeze' => MemberStatus::FROZEN,
            'suspend' => MemberStatus::SUSPENDED,
            'cancel' => MemberStatus::CANCELLED,
        ],
        MemberStatus::EXPIRED => [
            'renew' => MemberStatus::ACTIVE,
            'cancel' => MemberStatus::CANCELLED,
        ],
        MemberStatus::FROZEN => [
            'unfreeze' => MemberStatus::ACTIVE,
            'cancel' => MemberStatus::CANCELLED,
        ],
        MemberStatus::SUSPENDED => [
            'resume' => MemberStatus::ACTIVE,
            'cancel' => MemberStatus::CANCELLED,
        ],
    ];

    public function canTransition($fromStatus, $action)
    {
        return isset($this->transitions[$fromStatus][$action]);
    }

    public function transition($memberId, $action, $reason = '')
    {
        $member = Member::findOne($memberId);
        if (!$member) throw new Exception('会员不存在');

        if (!$this->canTransition($member->status, $action)) {
            throw new Exception("状态 {$member->status} 不允许执行 {$action}");
        }

        $toStatus = $this->transitions[$member->status][$action];
        $oldStatus = $member->status;

        // 原子更新状态
        $updated = Member::updateAll(
            ['status' => $toStatus, 'updated_at' => time()],
            ['id' => $memberId, 'status' => $oldStatus] // 乐观锁
        );
        if ($updated == 0) {
            throw new Exception('状态已变更，请重试');
        }

        // 记录状态变更日志
        $this->logTransition($memberId, $oldStatus, $toStatus, $action, $reason);

        // 触发后置动作（如发通知、清缓存）
        $this->triggerAfterTransition($memberId, $action, $oldStatus, $toStatus);

        return true;
    }
}
```

关键点：
- **流转规则配置化**：允许的状态流转在配置里定义，不允许的流转直接拒绝
- **乐观锁**：更新时带 `WHERE status = oldStatus`，防止并发变更
- **变更日志**：每次状态变更都记录，可追溯
- **后置动作**：状态变更后触发通知、清缓存等动作

### 2.4 状态变更日志

```sql
CREATE TABLE `member_status_log` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `member_id` int(11) NOT NULL,
  `old_status` varchar(20) NOT NULL,
  `new_status` varchar(20) NOT NULL,
  `action` varchar(30) NOT NULL COMMENT '操作：activate/expire/freeze/...',
  `reason` varchar(255) DEFAULT NULL COMMENT '变更原因',
  `operator_id` int(11) DEFAULT NULL COMMENT '操作人（系统/管理员/用户）',
  `operator_type` varchar(20) DEFAULT NULL COMMENT '操作人类型',
  `created_at` int(11) NOT NULL,
  PRIMARY KEY (`id`),
  KEY `member_id` (`member_id`),
  KEY `created_at` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

## 三、业务集成

### 3.1 会员可用判断

封装统一的可用判断方法，不再到处写 if-else：

```php
class MemberService
{
    public function isAvailable($memberId)
    {
        $member = Member::findOne($memberId);
        if (!$member) return false;

        // 只有 active 状态可用
        if ($member->status != MemberStatus::ACTIVE) return false;

        // 检查过期时间
        if ($member->expire_time > 0 && $member->expire_time < time()) {
            return false;
        }

        return true;
    }

    // 统一的权限校验入口
    public function checkAvailable($memberId)
    {
        if (!$this->isAvailable($memberId)) {
            throw new MemberNotAvailableException('会员状态不可用');
        }
        return true;
    }
}
```

### 3.2 定时过期检查

定时任务检查过期会员，自动变更状态：

```php
public function actionCheckExpire()
{
    $expiredMembers = Member::find()
        ->where(['status' => MemberStatus::ACTIVE])
        ->andWhere(['>', 'expire_time', 0])
        ->andWhere(['<', 'expire_time', time()])
        ->all();

    foreach ($expiredMembers as $member) {
        try {
            $this->stateMachine->transition($member->id, 'expire', '会员到期自动过期');
        } catch (Exception $e) {
            Yii::error("会员过期失败: {$member->id} - " . $e->getMessage());
        }
    }
}
```

## 四、踩坑经验

**1. 状态流转循环**：配置流转规则时要注意不要形成循环（如 active → expired → active 是正常的续费循环，但 active → frozen → active → frozen 无限循环要避免）。

**2. 并发状态变更**：两个请求同时变更同一个会员状态，乐观锁能防止数据错乱，但要处理好重试逻辑，给用户友好的提示。

**3. 后置动作失败**：状态变更成功但后置动作（如发通知）失败，不能回滚状态变更。用消息队列异步处理后置动作，失败重试，保证最终一致。

**4. 历史数据兼容**：1.0 版本的状态值和 2.0 不一致，要做数据迁移，把旧状态映射到新状态。

## 五、总结

基于状态机的会员生命周期管理核心经验：

1. **状态显式化**：所有状态明确定义，不允许隐式状态（如"过期但 status 还是 active"）
2. **流转规则化**：允许的状态流转在配置里定义，不允许的直接拒绝
3. **变更原子化**：乐观锁保证并发安全，状态变更原子操作
4. **日志可追溯**：每次状态变更都记录，出问题能查到原因
5. **动作后置化**：状态变更后的通知、清缓存等动作用消息队列异步处理
6. **判断统一化**：会员可用判断封装成统一方法，不在业务代码里散写 if-else

状态机不是银弹，适合状态多、流转复杂的场景。如果只有两三个状态、流转简单，用简单的 if-else 反而更直接。技术选型要根据实际复杂度，不要为了用状态机而用状态机。
