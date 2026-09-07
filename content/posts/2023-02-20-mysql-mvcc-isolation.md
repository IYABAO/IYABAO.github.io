---
title: "MySQL MVCC 与隔离级别：读懂 InnoDB 的读一致性"
date: 2023-02-20T09:00:00+08:00
lastmod: 2023-02-20T09:00:00+08:00
draft: false
author: IYABAO
tags:
  - MySQL
  - MVCC
  - InnoDB
categories:
  - 技术
summary: "为什么 RR 隔离级别下你读不到别人未提交的数据？MVCC、隐藏列、undo log、Read View——把 InnoDB 的读一致性问题一次讲透。"
---

# MySQL MVCC 与隔离级别：读懂 InnoDB 的读一致性

"为什么我在 RR（可重复读）隔离级别下，读不到别人刚提交的数据？""为什么 A 事务删了 100 行，B 事务还能查到？"——这些问题的答案都在 MVCC（多版本并发控制）里。

## 一、MVCC 要解决什么

并发事务读写同一行，如果没有控制，会出现：

- **脏读**：读到别人未提交的数据
- **不可重复读**：同一查询两次结果不同（别人提交了）
- **幻读**：同一范围查询两次，行数变了

MVCC 的思路：**读不阻塞写、写不阻塞读**——每个事务看到的是"自己的快照"，通过版本链实现，而不是靠锁硬排队。

## 二、InnoDB 的隐藏列

InnoDB 每行有 3 个隐藏列：

```
DB_TRX_ID  最近修改该行的事务 ID
DB_ROLL_PTR 回滚指针，指向 undo log 中的旧版本
DB_ROW_ID  单调递增的行 ID（无主键时用）
```

**关键：DB_ROLL_PTR 串起来的版本链**——同一行的多个版本通过回滚指针连成链表，旧版本数据存在 undo log 里。

```
行 v3（最新）：DB_TRX_ID=100, DB_ROLL_PTR → v2
行 v2：        DB_TRX_ID=80,  DB_ROLL_PTR → v1
行 v1（最旧）： DB_TRX_ID=50,  DB_ROLL_PTR → NULL
```

## 三、Read View：事务的快照

事务启动（第一次快照读）时生成 Read View，记录：

```
creator_trx_id  当前事务 ID
m_ids           活跃事务 ID 列表（还没提交的）
min_trx_id       活跃事务中最小的 ID
max_trx_id       下一个要分配的事务 ID（上界）
```

**判断一行版本是否可见**（核心规则）：

```
1. 版本 trx_id < min_trx_id → 已提交，可见 ✅
2. 版本 trx_id >= max_trx_id → 当前事务之后开启的，不可见 ❌
3. min_trx_id <= trx_id < max_trx_id：
   - 在 m_ids 中（活跃未提交）→ 不可见，沿回滚指针找旧版本
   - 不在 m_ids 中 → 已提交，可见 ✅
4. trx_id == creator_trx_id → 自己改的，可见 ✅
```

## 四、隔离级别的 MVCC 差异

| 隔离级别 | 快照读时机 | 效果 |
|---|---|---|
| READ COMMITTED | **每次查询**生成新 Read View | 能读到别人新提交的（不可重复读） |
| REPEATABLE READ | **事务首次查询**生成 Read View，之后复用 | 整个事务看到同一快照（可重复读） |

**这就是"RR 下读不到别人刚提交的数据"的原因**：Read View 是事务开始时定格的，后续查询都用同一个视图，别人提交了对它不可见。

### 幻读的残余问题

RR 的快照读解决了"查询结果不变"，但**当前读**（`SELECT ... FOR UPDATE` / `UPDATE` / `DELETE`）走的是另一条路：**当前读 + 间隙锁**。

```
RR 下：
快照读（普通 SELECT）→ 由 MVCC 保证一致 ✅
当前读（FOR UPDATE）→ 走索引锁 + 间隙锁，防止插入 ✅
```

**间隙锁**：锁定一个范围（比如 `age BETWEEN 20 AND 30`），阻止其他事务在这个范围插入——这就是 RR 防幻读的机制（牺牲部分并发）。

## 五、undo log 与版本链的代价

MVCC 不是免费的：

```
每行多次更新 → 版本链变长 → 查询要沿链找可见版本 → 变慢
undo log 膨胀 → 磁盘占用上升
长事务 → undo 无法 purge → 版本链长期保留
```

**实践**：

1. **长事务是 MVCC 的头号杀手**：一个事务开 10 分钟，undo 不能清理，版本链膨胀，同表其他查询全变慢
2. **监控 undo 大小**：`information_schema.innodb_metrics` 或 `SHOW ENGINE INNODB STATUS`
3. **避免高频更新同一行**：热点行版本链巨长，查询性能雪崩

## 六、实战问答

**Q：A 事务改了 100 行未提交，B 事务 SELECT 为什么看不到？**
A：B 的 Read View 里 A 在 m_ids（活跃）中，沿版本链找到旧版本 → 看不到新值。**这就是"读不阻塞写"的体现**——A 没提交，B 读到旧快照，双方互不阻塞。

**Q：为什么 RR 下 UPDATE 会锁冲突？**
A：UPDATE 是当前读，走索引锁 + 版本链更新。两个事务 UPDATE 同一行，后到的要等前一个提交——**写写冲突还是要等锁，MVCC 只解决读写互不阻塞**。

## 总结

MVCC 的完整认知：

1. **版本链**：隐藏列 + undo log，一行多版本
2. **Read View**：快照读的可见性判断规则
3. **RR 靠"复用 Read View"**，RC 靠"每次新视图"
4. **幻读**：当前读靠间隙锁兜底
5. **代价**：长事务 = 版本链膨胀 = 性能杀手

**MVCC 的本质是用空间（多版本）换并发（读写不阻塞）。** 理解它，你就能解释 90% 的"读不到/读得到"问题，也能设计出不踩长事务坑的业务。
