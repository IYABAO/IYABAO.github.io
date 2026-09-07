---
title: "Redis 分布式锁：从 SETNX 到 Redlock 的完整指南"
date: 2022-03-30T09:00:00+08:00
lastmod: 2022-03-30T09:00:00+08:00
draft: false
author: IYABAO
tags:
  - Redis
  - 分布式锁
  - 分布式
categories:
  - 技术
summary: "分布式锁是'看着简单、用起来全是坑'的典型。SETNX 的坑、锁过期竞态、可重入、Redlock 的争议，以及什么时候其实不需要分布式锁。"
---

# Redis 分布式锁：从 SETNX 到 Redlock 的完整指南

分布式锁是每个后端都要面对的东西，也是最容易被写错的东西。网上随便一搜都是"SETNX + 过期时间"的教程，但生产环境真正要用好，坑比教程多得多。

## 一、最基础的版本：SETNX + EXPIRE

```go
// 加锁：原子设置值 + 过期时间
// 必须用 SET ... NX EX，不能分两步（分两步锁会死）
ok, err := redis.Set(ctx, lockKey, token, redis.SetNX, redis.SetExpire(10*time.Second)).Result()
if ok {
    // 拿到锁
}

// 释放锁
// 必须校验持有者（token），防止误删别人的锁
script := `
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end`
redis.Eval(ctx, script, []string{lockKey}, token)
```

**三个必须**：

1. **加锁必须原子**：`SET key val NX EX 10` 一条命令，不能 SETNX 再 EXPIRE（中间崩溃锁永不过期）
2. **value 必须是唯一 token**：解锁时比对，防止"A 超时后 B 拿到锁，A 的解锁把 B 的锁删了"
3. **解锁必须 Lua**：GET + DEL 不是原子的，要放一个脚本里

## 二、核心难点：锁过期竞态

最经典的坑：

```
A 拿到锁，执行任务（业务耗时 12s）
锁 10s 过期 → 自动释放
B 拿到锁，开始执行同一任务
A 完成，释放锁（校验 token 是 A 的，没删到 B 的 ✅）
但此时 A、B 已经同时执行了任务 ❌
```

**解法 1：看门狗（续期）**

```go
// 后台 goroutine 每 1/3 锁时间续期，直到任务完成
go func() {
    ticker := time.NewTicker(3 * time.Second)
    defer ticker.Stop()
    for range ticker.C {
        // Lua：token 匹配则续期（类似 Redisson 的 watchdog）
        if !renew(ctx, lockKey, token, 10*time.Second) {
            break  // 锁已丢失，停止续期
        }
    }
}()
```

**解法 2：任务侧幂等（最稳）**

**锁只是"减少冲突"，不是"保证不冲突"**。业务上做幂等（唯一键、状态校验），锁丢了也不会产生重复副作用。这是最可靠的兜底。

## 三、可重入锁

同一个 goroutine 递归调用需要重入。Redis 没有原生重入，用 Lua 记录持有次数：

```lua
-- 可重入：key 存 {token, count}
if redis.call("get", KEYS[1]) == ARGV[1] then
    redis.call("incr", KEYS[1] .. ":count")
    return 1
end
```

**注意**：重入计数和锁过期要一起处理，否则重入 3 次后锁过期，计数残留。复杂场景建议直接用 Redisson（Java）/ redsync（Go）这类成熟库。

## 四、Redlock：争议很大的"强"方案

Redis 作者提出的 Redlock：向 N 个独立 Redis 节点加锁，**超过半数成功才算拿到锁**。

```go
// redsync 用法
mu := redsync.NewMutex("lock:task", redsync.WithExpiry(10*time.Second))
if err := mu.Lock(); err != nil {
    return err
}
defer mu.Unlock()
```

**争议**：分布式系统专家（Martin Kleppmann）批评 Redlock 在"时钟跳跃 + GC 停顿"下不成立。真实场景：

- **能用单实例锁就别用 Redlock**：绝大多数业务，单 Redis（主从）锁足够
- **Redlock 只适合"强一致 + 多副本"场景**：比如跨数据中心资源互斥
- **更简单的强方案**：`SETNX` 到单个 Redis + 业务幂等，比 Redlock 简单且够用

## 五、什么时候你其实不需要分布式锁

**这是最重要的一节**：

| 场景 | 真正解法 |
|---|---|
| 库存扣减 | Redis Lua 原子扣减（不是锁） |
| 防重复提交 | 唯一索引 / 幂等键（SETNX 当幂等，不是当锁） |
| 定时任务防重跑 | 数据库唯一约束 / 任务表状态 |
| 缓存重建 | 单飞（singleflight），比锁更高效 |
| 跨节点互斥 | 才需要真分布式锁 |

**分布式锁是最后手段**。90% 的"并发问题"用"原子操作 + 幂等"就能解决，不需要锁——锁会带来性能损耗、死锁风险、续期复杂度。

## 总结

Redis 分布式锁的完整认知：

1. **最小可用**：`SET NX EX` + token 校验 + Lua 解锁
2. **过期竞态**：看门狗续期 + 业务幂等兜底（幂等是根，锁是叶子）
3. **可重入**：计数 Lua 或成熟库
4. **Redlock**：争议大，单实例锁 + 幂等通常就够
5. **最重要**：先想清楚要不要锁——原子操作 + 幂等能解决就别上锁

**锁是复杂度的来源，能不用就不用。** 这句话价值超过上面所有代码。
