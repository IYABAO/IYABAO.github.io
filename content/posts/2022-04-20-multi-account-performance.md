---
title: "分账号系统性能优化：从 SQL 优化到缓存策略的全链路改造"
date: 2022-04-20T14:00:00+08:00
draft: false
tags: ["性能优化", "SQL优化", "Redis", "缓存", "PHP", "MySQL"]
categories: ["性能优化"]
summary: "分账号系统性能优化的完整实践，从慢 SQL 排查、索引优化到多级缓存策略，接口响应时间从 800ms 降到 80ms，数据库压力降低 60%。"
---

分账号系统上线后，随着企业数量增长，性能问题逐渐暴露——账号列表接口响应慢、权限校验频繁查库、大公司的账号管理页面经常超时。2022年4月做了一次全链路性能优化，接口响应时间从平均 800ms 降到 80ms，数据库压力降低 60%。今天把优化过程分享出来。

## 一、问题定位

先看监控，找到瓶颈：

1. **慢 SQL**：账号列表查询关联了角色、部门、数据范围等多张表，JOIN 多，扫描行数大
2. **N+1 查询**：列表页每个账号都单独查角色名、部门名，100 条数据就是 300 次查询
3. **权限缓存缺失**：每次接口调用都查权限表，权限变更频率低但查询频率极高
4. **没有分页**：大公司有几百个账号，一次性查全部，内存和响应都慢

## 二、SQL 优化

### 2.1 消除 N+1 查询

用 `WITH` 预加载，一次查询把关联数据都查出来：

```php
// 优化前：N+1 查询
$accounts = Account::find()->where(['company_id' => $companyId])->all();
foreach ($accounts as $account) {
    $roles = $account->roles; // 每条都查一次
    $dept = $account->department; // 每条都查一次
}

// 优化后：WITH 预加载
$accounts = Account::find()
    ->where(['company_id' => $companyId])
    ->with(['roles', 'department'])
    ->all();
```

Yii2 的 `with()` 会用 `IN` 查询一次性查出所有关联数据，100 条数据从 300 次查询降到 3 次。

### 2.2 索引优化

用 EXPLAIN 分析慢查询，发现几个关键查询没走索引：

```sql
-- 账号列表按创建时间排序，没加联合索引
ALTER TABLE account ADD INDEX idx_company_status_created (company_id, status, created_at);

-- 账号角色关联查询
ALTER TABLE account_role ADD INDEX idx_account (account_id);

-- 角色权限关联查询
ALTER TABLE role_permission ADD INDEX idx_role (role_id);
```

加了联合索引后，账号列表查询从全表扫描变成索引范围扫描，扫描行数从几万降到几百。

### 2.3 分页优化

账号列表加分页，避免一次性查全部数据：

```php
$page = Yii::$app->request->get('page', 1);
$pageSize = Yii::$app->request->get('page_size', 20);

$query = Account::find()
    ->where(['company_id' => $companyId])
    ->with(['roles', 'department']);

$count = $query->count();
$list = $query
    ->offset(($page - 1) * $pageSize)
    ->limit($pageSize)
    ->orderBy(['created_at' => SORT_DESC])
    ->all();
```

大公司有 500+ 账号，分页后每次只查 20 条，响应时间从 2 秒降到 100ms。

## 三、缓存策略

### 3.1 权限缓存

权限变更频率低但查询频率极高，用 Redis 缓存：

```php
class PermissionService
{
    public function getAccountPermissions($accountId)
    {
        $cacheKey = "perm:account:{$accountId}";
        $cached = Yii::$app->redis->get($cacheKey);
        if ($cached !== false) {
            return json_decode($cached, true);
        }

        $permissions = $this->queryFromDb($accountId);
        Yii::$app->redis->setex($cacheKey, 3600, json_encode($permissions));
        return $permissions;
    }

    public function clearCache($accountId)
    {
        Yii::$app->redis->del("perm:account:{$accountId}");
    }
}
```

权限校验从每次查数据库（5-10ms）变成查 Redis（0.1ms），性能提升 50-100 倍。

### 3.2 账号列表缓存

账号列表变更不频繁，用缓存 + 失效策略：

```php
public function getAccountList($companyId, $page, $pageSize)
{
    $cacheKey = "account:list:{$companyId}:{$page}:{$pageSize}";
    $cached = Yii::$app->redis->get($cacheKey);
    if ($cached !== false) {
        return json_decode($cached, true);
    }

    $list = $this->queryFromDb($companyId, $page, $pageSize);
    Yii::$app->redis->setex($cacheKey, 300, json_encode($list)); // 5分钟过期
    return $list;
}

// 账号变更时清缓存
public function clearListCache($companyId)
{
    $keys = Yii::$app->redis->keys("account:list:{$companyId}:*");
    foreach ($keys as $key) {
        Yii::$app->redis->del($key);
    }
}
```

### 3.3 多级缓存

热点数据用本地缓存（APCu）+ Redis 两级缓存：

```php
public function getRole($roleId)
{
    // 一级缓存：本地内存，微秒级
    $local = apcu_fetch("role:{$roleId}");
    if ($local !== false) return $local;

    // 二级缓存：Redis，毫秒级
    $redis = Yii::$app->redis->get("role:{$roleId}");
    if ($redis !== false) {
        $role = json_decode($redis, true);
        apcu_store("role:{$roleId}", $role, 60); // 本地缓存1分钟
        return $role;
    }

    // 三级：数据库
    $role = Role::findOne($roleId)->toArray();
    Yii::$app->redis->setex("role:{$roleId}", 3600, json_encode($role));
    apcu_store("role:{$roleId}", $role, 60);
    return $role;
}
```

## 四、其他优化

### 4.1 只查需要的字段

列表页不需要返回所有字段，只查需要的：

```php
// 优化前：查所有字段
$accounts = Account::find()->all();

// 优化后：只查需要的字段
$accounts = Account::find()
    ->select(['id', 'username', 'real_name', 'email', 'status', 'created_at'])
    ->all();
```

减少网络传输和内存占用，性能提升明显。

### 4.2 批量操作

批量创建/更新账号，用批量插入减少数据库交互：

```php
// 优化前：循环插入
foreach ($data as $item) {
    $model = new Account($item);
    $model->save(); // 每次一次 INSERT
}

// 优化后：批量插入
Yii::$app->db->createCommand()
    ->batchInsert('account', ['username', 'real_name', 'company_id'], $data)
    ->execute(); // 一次 INSERT
```

100 条数据从 100 次 INSERT 变成 1 次，性能提升几十倍。

### 4.3 读写分离

查询走从库，写入走主库，减轻主库压力：

```php
// Yii2 配置读写分离
'components' => [
    'db' => [
        'class' => 'yii\db\Connection',
        'masterConfig' => ['dsn' => 'mysql:host=master;dbname=db'],
        'slaveConfig' => ['dsn' => 'mysql:host=slave;dbname=db'],
        'masters' => [[]],
        'slaves' => [[]],
    ],
]
```

## 五、效果对比

| 指标 | 优化前 | 优化后 | 提升 |
|------|--------|--------|------|
| 账号列表响应时间 | 800ms | 80ms | 90%↓ |
| 权限校验耗时 | 10ms | 0.1ms | 99%↓ |
| 数据库 QPS | 1200 | 450 | 62%↓ |
| 慢查询数量（每天） | 50+ | 2-3 | 95%↓ |
| 大公司账号页加载时间 | 3s | 150ms | 95%↓ |

## 六、总结

分账号系统性能优化的核心经验：

1. **SQL 优化是基础**：消除 N+1 查询、加联合索引、分页，这些是性价比最高的优化
2. **缓存是关键**：权限、角色等低频变更高频查询的数据一定要缓存，多级缓存（本地+Redis）效果更好
3. **只查需要的**：列表页只查需要的字段，减少网络和内存开销
4. **批量操作**：批量插入/更新减少数据库交互次数
5. **读写分离**：查询走从库，减轻主库压力
6. **监控持续**：优化不是一次性的，要持续监控慢查询和性能指标

性能优化没有银弹，要从全链路分析，找到真正的瓶颈。有时候加个索引就能解决问题，有时候需要架构层面的改造。关键是用数据说话，先定位问题再优化，不要盲目优化。
