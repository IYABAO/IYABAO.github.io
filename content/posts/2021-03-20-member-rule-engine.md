---
title: "普通会员策略引擎重构：从硬编码到规则引擎的设计思路"
date: 2021-03-20T14:30:00+08:00
draft: false
tags: ["架构设计", "规则引擎", "PHP", "业务建模", "会员系统"]
categories: ["架构设计"]
summary: "招聘通普通会员策略系统从硬编码到规则引擎的重构实践，解决业务规则频繁变更导致的代码维护难题，实现策略配置化、热更新。"
---

招聘通的会员体系里，普通会员有各种权益限制：每天能刷新多少职位、能看多少简历、能下载多少联系方式、能发多少面试邀请。这些规则业务方经常改，一会说刷新次数从5次改成10次，一会说新用户前7天不限次数。最早是硬编码在代码里，每次改规则都要发版，烦不胜烦。2021年做了次重构，把会员策略抽成规则引擎，今天把设计思路分享出来。

## 一、原始方案的问题

最早的代码长这样：

```php
class MemberPrivilege
{
    public function canRefreshJob($userId)
    {
        $member = Member::findOne(['user_id' => $userId]);
        $todayCount = JobRefreshLog::find()
            ->where(['user_id' => $userId])
            ->andWhere(['>=', 'created_at', strtotime('today')])
            ->count();

        // 普通会员每天5次
        if ($member->level == 'normal') {
            return $todayCount < 5;
        }
        // VIP 不限
        return true;
    }

    public function canViewResume($userId)
    {
        // 类似的逻辑...
    }

    public function canDownloadContact($userId)
    {
        // 类似的逻辑...
    }
}
```

问题很明显：

1. **硬编码**：次数、条件都写死在代码里，改规则要改代码发版
2. **分散**：各种权益的判断逻辑散落在不同方法里，有的甚至散落在业务代码里
3. **不灵活**：加新规则（如新用户前7天不限次数）要写一堆 if-else
4. **无法热更新**：业务方想临时调整活动期间的权益，必须等发版
5. **测试困难**：各种规则组合太多，测试覆盖不全

## 二、规则引擎设计

核心思路：**把规则从代码里抽出来，变成数据，存储在数据库或配置中心，运行时动态加载和执行**。

### 2.1 规则模型

一条规则由三部分组成：
- **条件（Condition）**：什么情况下适用这条规则
- **动作（Action）**：满足条件时做什么（限制次数、放行、拒绝等）
- **优先级（Priority）**：多条规则同时满足时，优先级高的先执行

```sql
CREATE TABLE `member_rule` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `name` varchar(100) NOT NULL COMMENT '规则名称',
  `privilege_type` varchar(50) NOT NULL COMMENT '权益类型：refresh_job/view_resume/download_contact',
  `condition` text NOT NULL COMMENT '条件表达式（JSON）',
  `action` varchar(20) NOT NULL COMMENT '动作：allow/deny/limit',
  `limit_count` int(11) DEFAULT NULL COMMENT '限制次数（action=limit时有效）',
  `limit_period` varchar(20) DEFAULT NULL COMMENT '限制周期：day/week/month/total',
  `priority` int(11) NOT NULL DEFAULT '100' COMMENT '优先级，数字越大越优先',
  `status` tinyint(1) NOT NULL DEFAULT '1' COMMENT '1启用 0禁用',
  `start_time` int(11) DEFAULT NULL COMMENT '生效开始时间',
  `end_time` int(11) DEFAULT NULL COMMENT '生效结束时间',
  `created_at` int(11) NOT NULL,
  `updated_at` int(11) NOT NULL,
  PRIMARY KEY (`id`),
  KEY `privilege_type` (`privilege_type`),
  KEY `status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

### 2.2 条件表达式

条件用 JSON 表示，支持 AND/OR 嵌套和比较运算：

```json
{
  "operator": "AND",
  "conditions": [
    {"field": "member_level", "op": "==", "value": "normal"},
    {"field": "register_days", "op": ">=", "value": 7},
    {
      "operator": "OR",
      "conditions": [
        {"field": "is_new_user", "op": "==", "value": false},
        {"field": "activity_period", "op": "==", "value": false}
      ]
    }
  ]
}
```

支持的运算符：`==`, `!=`, `>`, `>=`, `<`, `<=`, `in`, `not_in`, `between`。

### 2.3 规则执行引擎

```php
class RuleEngine
{
    private $rules = [];

    public function __construct($privilegeType)
    {
        $this->loadRules($privilegeType);
    }

    private function loadRules($privilegeType)
    {
        // 从缓存或数据库加载启用的规则，按优先级排序
        $this->rules = MemberRule::find()
            ->where(['privilege_type' => $privilegeType, 'status' => 1])
            ->andWhere(['or', ['start_time' => null], ['<=', 'start_time', time()]])
            ->andWhere(['or', ['end_time' => null], ['>=', 'end_time', time()]])
            ->orderBy(['priority' => SORT_DESC])
            ->all();
    }

    public function evaluate($context)
    {
        foreach ($this->rules as $rule) {
            if ($this->matchCondition(json_decode($rule->condition, true), $context)) {
                return [
                    'action' => $rule->action,
                    'limit_count' => $rule->limit_count,
                    'limit_period' => $rule->limit_period,
                    'rule_id' => $rule->id,
                    'rule_name' => $rule->name,
                ];
            }
        }
        // 没有匹配的规则，默认放行
        return ['action' => 'allow'];
    }

    private function matchCondition($condition, $context)
    {
        if (isset($condition['operator'])) {
            // 复合条件
            $results = [];
            foreach ($condition['conditions'] as $sub) {
                $results[] = $this->matchCondition($sub, $context);
            }
            if ($condition['operator'] == 'AND') {
                return !in_array(false, $results, true);
            } else {
                return in_array(true, $results, true);
            }
        } else {
            // 原子条件
            $value = $context[$condition['field']] ?? null;
            return $this->compare($value, $condition['op'], $condition['value']);
        }
    }

    private function compare($value, $op, $target)
    {
        switch ($op) {
            case '==': return $value == $target;
            case '!=': return $value != $target;
            case '>': return $value > $target;
            case '>=': return $value >= $target;
            case '<': return $value < $target;
            case '<=': return $value <= $target;
            case 'in': return in_array($value, (array)$target);
            case 'not_in': return !in_array($value, (array)$target);
            case 'between': return $value >= $target[0] && $value <= $target[1];
            default: return false;
        }
    }
}
```

### 2.4 权益校验服务

```php
class PrivilegeService
{
    public function check($userId, $privilegeType)
    {
        // 构建上下文
        $context = $this->buildContext($userId);

        // 执行规则引擎
        $engine = new RuleEngine($privilegeType);
        $result = $engine->evaluate($context);

        if ($result['action'] == 'deny') {
            return ['allowed' => false, 'reason' => '权限不足', 'rule' => $result['rule_name']];
        }

        if ($result['action'] == 'limit') {
            $used = $this->getUsedCount($userId, $privilegeType, $result['limit_period']);
            $remaining = $result['limit_count'] - $used;
            return [
                'allowed' => $remaining > 0,
                'limit' => $result['limit_count'],
                'used' => $used,
                'remaining' => max(0, $remaining),
                'rule' => $result['rule_name'],
            ];
        }

        // allow
        return ['allowed' => true, 'limit' => -1, 'remaining' => -1];
    }

    private function buildContext($userId)
    {
        $member = Member::findOne(['user_id' => $userId]);
        return [
            'user_id' => $userId,
            'member_level' => $member->level,
            'register_days' => floor((time() - $member->created_at) / 86400),
            'is_new_user' => (time() - $member->created_at) < 86400 * 7,
            'activity_period' => $this->isActivityPeriod(),
            // ... 更多上下文字段
        ];
    }

    private function getUsedCount($userId, $privilegeType, $period)
    {
        $startTime = $this->getPeriodStart($period);
        return PrivilegeLog::find()
            ->where(['user_id' => $userId, 'privilege_type' => $privilegeType])
            ->andWhere(['>=', 'created_at', $startTime])
            ->count();
    }
}
```

## 三、规则配置后台

做了个简单的后台页面，运营人员可以可视化配置规则：

- 规则列表：查看所有规则，启用/禁用，调整优先级
- 规则编辑：选择权益类型，配置条件（可视化表单），设置动作和限制
- 规则测试：输入用户ID，模拟执行，看哪条规则命中、结果是什么
- 变更记录：记录规则的变更历史，支持回滚

条件配置用可视化表单，运营人员不需要写 JSON，选择字段、运算符、值就行，后台自动转成 JSON 存储。

## 四、缓存与热更新

规则变更后要立即生效，不能等缓存过期。

```php
class RuleCache
{
    const CACHE_KEY = 'member_rules';
    const CACHE_TTL = 3600;

    public static function get($privilegeType)
    {
        $redis = Yii::$app->redis;
        $key = self::CACHE_KEY . ':' . $privilegeType;
        $data = $redis->get($key);
        if ($data !== false) {
            return json_decode($data, true);
        }

        $rules = MemberRule::find()
            ->where(['privilege_type' => $privilegeType, 'status' => 1])
            ->orderBy(['priority' => SORT_DESC])
            ->asArray()
            ->all();

        $redis->setex($key, self::CACHE_TTL, json_encode($rules));
        return $rules;
    }

    public static function clear($privilegeType = null)
    {
        $redis = Yii::$app->redis;
        if ($privilegeType) {
            $redis->del(self::CACHE_KEY . ':' . $privilegeType);
        } else {
            // 清所有
            $keys = $redis->keys(self::CACHE_KEY . ':*');
            foreach ($keys as $key) {
                $redis->del($key);
            }
        }
    }
}
```

规则保存时调用 `RuleCache::clear()` 清缓存，下次请求时重新加载，实现热更新。

## 五、踩过的坑

**1. 规则优先级冲突**

两条规则条件有重叠，优先级设置不合理，导致命中了错误的规则。后来加了规则测试功能，配置规则时可以模拟执行，确认命中的是预期规则。

**2. 条件表达式解析性能**

每次请求都解析 JSON 条件、递归匹配，QPS 高的时候有性能开销。后来把规则和解析后的条件树都缓存起来，避免重复解析。

**3. 次数统计的并发问题**

限制次数的权益，高并发下同时请求可能超过限制（两个请求同时查到剩余1次，都放行）。用 Redis 原子计数（INCR）替代数据库 COUNT，限制判断和计数在一个原子操作里完成。

**4. 规则变更的灰度**

运营改规则后直接全量生效，有次改错了导致所有普通会员都不能刷新职位。后来加了灰度功能，规则可以先对部分企业生效，观察没问题再全量。

**5. 上下文构建的开销**

每次校验都要查会员信息、注册天数等，构建上下文有数据库查询。把上下文信息缓存到 Redis，用户信息变更时更新缓存，减少数据库查询。

## 六、总结

会员策略引擎重构的核心思路：

1. **规则数据化**：把硬编码的 if-else 变成数据库里的规则记录
2. **条件表达式**：用 JSON 表示复杂条件，支持 AND/OR 嵌套和多种运算符
3. **规则引擎**：通用的条件匹配和规则执行逻辑，新增规则不用改代码
4. **配置化后台**：运营人员可视化配置规则，支持测试和灰度
5. **热更新**：规则变更即时生效，不用发版
6. **缓存优化**：规则和上下文缓存，减少数据库查询和解析开销

重构后，业务方改规则不用找开发了，自己在后台配置就行，即时生效。开发也不用每次改几个数字就发版，省心很多。

规则引擎不是银弹，适合规则频繁变更、条件复杂的场景。如果规则很简单且基本不变，硬编码反而更直接。技术选型要根据实际情况，不要为了用规则引擎而用规则引擎。
