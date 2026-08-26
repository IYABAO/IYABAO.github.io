---
title: "Redis 分布式锁在高并发场景下的正确性分析：从 Redlock 到原子防重"
date: 2021-09-25T15:30:00+08:00
draft: false
tags: ["Redis", "分布式锁", "高并发", "PHP", "Redlock", "幂等"]
categories: ["分布式系统"]
summary: "Redis 分布式锁在高并发场景下的正确性分析，从基础的 SETNX 到 Redlock 算法，再到原子防重的工程实践，分析各种方案的适用场景和坑点。"
---

分布式锁是高并发系统里的常用工具，防止多个进程同时操作共享资源。Redis 因为性能高、实现简单，是最常用的分布式锁方案。但 Redis 分布式锁的正确性一直有争议，Martin Kleppmann 和 antirez（Redis 作者）还专门争论过 Redlock 算法的安全性。今天从工程实践角度，分析 Redis 分布式锁在高并发场景下的各种方案和坑点。

## 一、基础实现：SETNX

最简单的分布式锁：

```php
$lockKey = "lock:job:{$jobId}";
$locked = $redis->setnx($lockKey, 1);
if (!$locked) {
    throw new Exception('操作太频繁，请稍后再试');
}
try {
    // 业务逻辑
} finally {
    $redis->del($lockKey);
}
```

问题很明显：
1. **没有过期时间**：如果进程崩溃，锁永远不释放，死锁
2. **不是原子操作**：SETNX + EXPIRE 分两步，中间崩溃会导致锁没有过期时间

## 二、改进版：SET 原子操作

Redis 2.6.12 之后，SET 命令支持 NX 和 EX 参数，原子操作：

```php
$lockKey = "lock:job:{$jobId}";
$requestId = uniqid(); // 唯一标识，防止误删别人的锁
$locked = $redis->set($lockKey, $requestId, ['NX', 'EX' => 30]);
if (!$locked) {
    throw new Exception('操作太频繁，请稍后再试');
}
try {
    // 业务逻辑
} finally {
    // 只删除自己的锁
    $script = <<<LUA
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
else
    return 0
end
LUA;
    $redis->eval($script, [$lockKey, $requestId], 1);
}
```

关键点：
1. **SET NX EX 原子操作**：加锁和设置过期时间一步完成，避免死锁
2. **requestId 唯一标识**：每个锁有唯一值，释放时校验，防止误删别人的锁
3. **Lua 脚本原子释放**：GET + DEL 用 Lua 脚本保证原子性，避免"GET 发现是自己的锁 → 锁过期被别人获取 → DEL 删了别人的锁"的竞态

这个方案在单 Redis 实例下是正确的，大部分场景够用。但在 Redis 主从架构下有问题。

## 三、主从架构的问题

Redis 主从复制是异步的。加锁后，主节点还没把锁同步到从节点就挂了，从节点升为主节点，锁就丢了。两个进程可能同时获取到锁。

场景：
1. 进程 A 在主节点获取锁
2. 主节点挂了，锁还没同步到从节点
3. 从节点升为主节点
4. 进程 B 在新主节点获取锁
5. A 和 B 同时持有锁，分布式锁失效

这个问题发生概率低，但在高并发、对正确性要求高的场景下不能忽视。

## 四、Redlock 算法

Redis 作者 antirez 提出的 Redlock 算法，解决主从架构下的锁丢失问题。

### 4.1 算法原理

部署 N 个独立的 Redis 实例（通常 5 个），互相之间不同步。加锁时：

1. 获取当前时间戳
2. 依次向 N 个实例请求加锁，用相同的 key 和 requestId，设置较短的超时时间（如 50ms）
3. 计算获取锁的总耗时 = 当前时间 - 开始时间
4. 如果超过半数（N/2+1）实例加锁成功，且总耗时 < 锁的有效时间，认为加锁成功
5. 否则认为加锁失败，向所有实例发送解锁命令

### 4.2 PHP 实现

```php
class RedLock
{
    private $redisInstances = [];
    private $quorum;
    private $lockTimeout = 30000; // 锁超时30秒
    private $retryDelay = 200; // 重试延迟200ms
    private $retryCount = 3; // 重试3次

    public function __construct(array $redisConfigs)
    {
        foreach ($redisConfigs as $config) {
            $redis = new Redis();
            $redis->connect($config['host'], $config['port'], 0.05); // 50ms超时
            $this->redisInstances[] = $redis;
        }
        $this->quorum = count($this->redisInstances) / 2 + 1;
    }

    public function lock($resource, $ttl = 30000)
    {
        $requestId = uniqid('', true);
        $key = "lock:{$resource}";

        for ($retry = 0; $retry < $this->retryCount; $retry++) {
            $startTime = microtime(true) * 1000;
            $successCount = 0;

            // 向所有实例加锁
            foreach ($this->redisInstances as $redis) {
                try {
                    $locked = $redis->set($key, $requestId, ['NX', 'PX' => $ttl]);
                    if ($locked) $successCount++;
                } catch (Exception $e) {
                    // 实例不可用，跳过
                }
            }

            $elapsedTime = microtime(true) * 1000 - $startTime;
            $validityTime = $ttl - $elapsedTime;

            // 超过半数成功且有效时间 > 0
            if ($successCount >= $this->quorum && $validityTime > 0) {
                return [
                    'resource' => $resource,
                    'request_id' => $requestId,
                    'validity_time' => $validityTime,
                ];
            }

            // 失败，释放所有实例的锁
            $this->unlock($key, $requestId);

            // 随机延迟后重试
            usleep($this->retryDelay * 1000 + rand(0, 100000));
        }

        return false;
    }

    public function unlock($lock)
    {
        $key = "lock:{$lock['resource']}";
        $requestId = $lock['request_id'];

        $script = <<<LUA
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
else
    return 0
end
LUA;

        foreach ($this->redisInstances as $redis) {
            try {
                $redis->eval($script, [$key, $requestId], 1);
            } catch (Exception $e) {
                // 忽略
            }
        }
    }
}
```

### 4.3 Redlock 的争议

Martin Kleppmann 认为 Redlock 不安全，核心论点：
1. **依赖时间**：Redlock 的正确性依赖各节点时钟同步，时钟漂移可能导致锁提前过期
2. **GC 停顿**：进程获取锁后发生 GC 停顿，停顿期间锁过期被别人获取，GC 恢复后进程以为自己还持有锁
3. **网络分区**：网络分区可能导致脑裂，两边都认为自己获取了锁

antirez 的回应：
1. 时钟漂移在实际环境中可控，Redis 的过期时间是单调递增的
2. GC 停顿问题在任何分布式锁方案中都存在，不是 Redlock 特有的
3. 多数派算法本身就能处理网络分区

这个争论没有绝对的对错，关键看业务场景。如果业务能容忍极低概率的锁冲突（如库存扣减有数据库唯一索引兜底），单实例 Redis 锁就够了。如果对正确性要求极高，应该用 ZooKeeper 或 etcd 等强一致性的分布式锁。

## 五、工程实践：原子防重

很多场景下，我们需要的不是严格的分布式锁，而是"防止重复提交/重复操作"。这种场景用原子防重更简单可靠。

### 5.1 基于唯一键的防重

数据库唯一索引是最可靠的防重手段：

```sql
ALTER TABLE job_apply ADD UNIQUE KEY uk_user_job (user_id, job_id);
```

重复投递时，数据库会报唯一键冲突，应用层捕获后返回"已投递"。这是最终一致性的保障，任何缓存层的防重都可能失效，数据库唯一索引是最后一道防线。

### 5.2 基于 Redis 的原子防重

```php
class IdempotencyService
{
    public function checkAndSet($key, $ttl = 86400)
    {
        // SETNX 原子操作，成功返回 true，失败返回 false
        return $this->redis->set($key, 1, ['NX', 'EX' => $ttl]) !== false;
    }

    public function isDuplicate($key)
    {
        return !$this->checkAndSet($key);
    }
}
```

使用：

```php
$idempotencyKey = "apply:{$userId}:{$jobId}";
if (IdempotencyService::isDuplicate($idempotencyKey)) {
    return ['code' => 2001, 'message' => '已经投递过该职位'];
}

// 执行投递逻辑
// ...
```

### 5.3 防重 vs 锁的区别

| 维度 | 分布式锁 | 原子防重 |
|------|---------|---------|
| 目的 | 互斥访问共享资源 | 防止重复操作 |
| 持有时间 | 业务执行期间 | 操作完成后长期保留 |
| 释放 | 业务完成后主动释放 | 靠 TTL 自动过期 |
| 失败处理 | 获取失败重试或等待 | 重复直接拒绝 |
| 适用场景 | 库存扣减、资源抢占 | 订单提交、投递防重 |

## 六、锁续期（看门狗）

业务执行时间可能超过锁的过期时间，导致锁提前释放。Redisson 的看门狗机制自动续期：

```php
class WatchDogLock
{
    private $redis;
    private $lockKey;
    $requestId;
    private $ttl = 30;
    private $renewInterval = 10; // 每10秒续期一次
    private $running = false;

    public function lock()
    {
        $this->requestId = uniqid();
        $locked = $this->redis->set($this->lockKey, $this->requestId, ['NX', 'EX' => $this->ttl]);
        if (!$locked) return false;

        // 启动看门狗线程续期
        $this->running = true;
        $this->startWatchDog();
        return true;
    }

    private function startWatchDog()
    {
        // PHP 没有真正的多线程，用定时任务或协程实现
        // 这里用 Swoole 定时器示例
        Swoole\Timer::tick($this->renewInterval * 1000, function () {
            if (!$this->running) return;
            // 续期：如果锁还是自己的，就延长过期时间
            $script = <<<LUA
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('expire', KEYS[1], ARGV[2])
else
    return 0
end
LUA;
            $this->redis->eval($script, [$this->lockKey, $this->requestId, $this->ttl], 1);
        });
    }

    public function unlock()
    {
        $this->running = false;
        // Lua 脚本释放锁
        // ...
    }
}
```

## 七、总结

Redis 分布式锁的工程实践要点：

1. **基础方案**：SET NX EX 原子加锁 + requestId 标识 + Lua 脚本原子释放，单实例场景够用
2. **高可用方案**：Redlock 多实例多数派，解决主从异步复制的锁丢失问题，但有争议
3. **防重场景**：原子防重（SETNX + TTL）比分布式锁更简单，配合数据库唯一索引兜底
4. **锁续期**：业务执行时间不确定时，用看门狗机制自动续期
5. **最终兜底**：任何缓存层的锁都可能失效，数据库唯一索引/乐观锁是最后一道防线

技术选型要根据业务场景：
- 能容忍极低概率冲突 → 单实例 Redis 锁
- 对正确性要求高 → Redlock 或 ZooKeeper/etcd
- 只是防重复提交 → 原子防重 + 数据库唯一索引

分布式锁不是银弹，能用数据库唯一索引/乐观锁解决的问题，不要引入分布式锁。分布式锁增加了系统复杂度，出问题排查困难。只有在数据库层面解决不了（如跨服务、跨数据库的资源互斥）时，才考虑用分布式锁。
