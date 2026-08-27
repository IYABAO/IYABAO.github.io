---
title: "分布式事务方案对比：Saga vs TCC vs 本地消息表选型"
date: 2025-03-25T14:00:00+08:00
draft: false
tags: ["分布式事务", "Saga", "TCC", "本地消息表", "微服务", "最终一致性"]
categories: ["架构设计"]
summary: "微服务架构下分布式事务的三种主流方案对比，Saga、TCC、本地消息表的原理、适用场景、优缺点，以及在招聘业务中的选型实践和踩坑经验。"
---

微服务拆分后，一个业务操作可能涉及多个服务的数据变更，比如"投递简历"要同时更新投递表、职位表、用户积分，这三个操作在不同服务里，怎么保证一致性？2025年我们在投递系统重构时深入调研了分布式事务方案，今天把对比和选型经验分享出来。

## 一、为什么需要分布式事务

单体应用里用数据库本地事务就能保证一致性：

```sql
BEGIN;
INSERT INTO apply (user_id, job_id) VALUES (1001, 2001);
UPDATE job SET apply_count = apply_count + 1 WHERE id = 2001;
UPDATE user SET points = points + 10 WHERE id = 1001;
COMMIT;
```

微服务拆分后，三个操作在三个服务里，各自有独立的数据库，没法用一个本地事务包起来。这时候需要分布式事务。

## 二、CAP 定理与最终一致性

分布式系统不可能同时满足 CAP（一致性、可用性、分区容错性），网络分区不可避免，所以只能在 CP 和 AP 之间选。

大部分互联网业务选 **AP + 最终一致性**——短时间内数据可能不一致，但最终会一致。用户投递简历后，职位投递数晚几秒更新完全可以接受，不需要强一致。

所以分布式事务的核心是**最终一致性**，不是强一致。

## 三、三种主流方案

### 方案一：Saga 模式

**原理**：把一个大事务拆成多个本地事务，每个本地事务有对应的补偿操作。如果某个步骤失败，按逆序执行前面步骤的补偿操作。

```
投递简历 Saga：
步骤1：创建投递记录（apply-service）
  补偿：删除投递记录
步骤2：更新职位投递数（job-service）
  补偿：投递数减1
步骤3：增加用户积分（user-service）
  补偿：扣减积分

执行：步骤1 → 步骤2 → 步骤3（全部成功）
失败：步骤1 → 步骤2（失败）→ 补偿步骤1（回滚）
```

**两种实现方式**：

1. **编排式（Orchestration）**：中央协调器控制流程，调用各服务，失败时调用补偿。适合复杂流程。
2. **协同式（Choreography）**：每个服务执行完发事件，下一个服务监听事件执行，失败时发补偿事件。适合简单流程。

**编排式实现**：

```java
// Saga 协调器
@Service
public class ApplySagaService {

    @Autowired
    private ApplyService applyService;
    @Autowired
    private JobService jobService;
    @Autowired
    private UserService userService;

    public void applyResume(Long userId, Long jobId) {
        // 步骤1：创建投递
        try {
            applyService.createApply(userId, jobId);
        } catch (Exception e) {
            throw new BusinessException("创建投递失败");
        }

        // 步骤2：更新职位投递数
        try {
            jobService.incrementApplyCount(jobId);
        } catch (Exception e) {
            // 补偿步骤1
            applyService.cancelApply(userId, jobId);
            throw new BusinessException("更新职位失败，已回滚投递");
        }

        // 步骤3：增加用户积分
        try {
            userService.addPoints(userId, 10);
        } catch (Exception e) {
            // 补偿步骤2和步骤1
            jobService.decrementApplyCount(jobId);
            applyService.cancelApply(userId, jobId);
            throw new BusinessException("增加积分失败，已全部回滚");
        }
    }
}
```

**优点**：
- 长事务也能支持，不锁资源
- 各服务独立，松耦合
- 适合业务流程长、参与服务多的场景

**缺点**：
- 没有隔离性，中间状态对外可见（比如投递创建了但职位数还没更新）
- 补偿逻辑复杂，每个操作都要写补偿
- 补偿操作本身可能失败，需要重试机制

**适用场景**：业务流程长、参与服务多、允许中间状态可见、对实时一致性要求不高。

---

### 方案二：TCC 模式

**原理**：每个服务提供三个接口——Try（预留资源）、Confirm（确认提交）、Cancel（取消回滚）。协调器先调用所有服务的 Try，全部成功则调用 Confirm，有失败则调用 Cancel。

```
投递简历 TCC：
Try 阶段：
  apply-service：预留投递记录（状态=待确认）
  job-service：预留投递数（冻结一个名额）
  user-service：预留积分（冻结10积分）

Confirm 阶段（全部Try成功）：
  apply-service：确认投递（状态=已确认）
  job-service：确认投递数+1
  user-service：确认积分+10

Cancel 阶段（有Try失败）：
  apply-service：取消投递（删除或状态=已取消）
  job-service：释放冻结名额
  user-service：释放冻结积分
```

**实现**：

```java
// apply-service 的 TCC 接口
@RestController
public class ApplyTccController {

    // Try：预留投递
    @PostMapping("/tcc/try")
    public boolean tryApply(@RequestBody ApplyRequest req) {
        // 检查是否可以投递（是否已投递、职位是否在招）
        if (alreadyApplied(req.getUserId(), req.getJobId())) {
            return false;
        }
        // 创建待确认的投递记录
        applyRepository.save(new Apply(req.getUserId(), req.getJobId(), "PENDING"));
        return true;
    }

    // Confirm：确认
    @PostMapping("/tcc/confirm")
    public boolean confirmApply(@RequestBody ApplyRequest req) {
        Apply apply = applyRepository.findByUserAndJob(req.getUserId(), req.getJobId());
        if (apply != null && apply.getStatus().equals("PENDING")) {
            apply.setStatus("CONFIRMED");
            applyRepository.save(apply);
        }
        return true;
    }

    // Cancel：取消
    @PostMapping("/tcc/cancel")
    public boolean cancelApply(@RequestBody ApplyRequest req) {
        Apply apply = applyRepository.findByUserAndJob(req.getUserId(), req.getJobId());
        if (apply != null && apply.getStatus().equals("PENDING")) {
            apply.setStatus("CANCELLED");
            applyRepository.save(apply);
        }
        return true;
    }
}
```

**优点**：
- 有隔离性，Try 阶段预留资源，中间状态不对外可见
- 一致性比 Saga 强
- 适合对一致性要求高的场景

**缺点**：
- 侵入性强，每个服务要写三个接口
- 开发成本高，业务逻辑复杂
- Try/Confirm/Cancel 都要保证幂等
- Confirm/Cancel 可能失败，需要重试和超时处理

**适用场景**：对一致性要求高、资源需要预留、金额/库存类场景（如支付、秒杀、库存扣减）。

---

### 方案三：本地消息表

**原理**：在本地事务里同时写业务数据和消息数据，然后异步消费消息调用其他服务。利用本地事务保证业务数据和消息一定同时成功，消息消费失败自动重试，最终一致。

```
投递简历本地消息表：
1. 本地事务：
   - INSERT INTO apply (...)  -- 写投递记录
   - INSERT INTO message (type, data, status) VALUES ('apply_created', '...', 'PENDING')  -- 写消息
   COMMIT

2. 异步任务扫描 PENDING 消息：
   - 调用 job-service 更新投递数
   - 调用 user-service 增加积分
   - 成功后标记消息为 PROCESSED
   - 失败则重试，超过最大次数进死信队列人工处理
```

**实现**：

```sql
-- 消息表
CREATE TABLE `message` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `type` varchar(50) NOT NULL COMMENT '消息类型',
  `data` text NOT NULL COMMENT '消息内容（JSON）',
  `status` varchar(20) NOT NULL DEFAULT 'PENDING' COMMENT 'PENDING/PROCESSED/FAILED',
  `retry_count` int(11) NOT NULL DEFAULT 0,
  `next_retry_time` int(11) DEFAULT NULL,
  `created_at` int(11) NOT NULL,
  `updated_at` int(11) NOT NULL,
  PRIMARY KEY (`id`),
  KEY `status_next_retry` (`status`, `next_retry_time`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

```java
@Service
public class ApplyService {

    @Transactional
    public void applyResume(Long userId, Long jobId) {
        // 1. 写业务数据
        applyRepository.createApply(userId, jobId);

        // 2. 写消息（和业务数据在同一个本地事务里）
        Message message = new Message();
        message.setType("apply_created");
        message.setData(JSON.toJSONString(Map.of("userId", userId, "jobId", jobId)));
        message.setStatus("PENDING");
        messageRepository.save(message);
    }
}

// 消息消费任务
@Component
public class MessageConsumer {

    @Scheduled(fixedDelay = 5000) // 每5秒扫描一次
    public void consume() {
        List<Message> messages = messageRepository.findPendingMessages(100);
        for (Message msg : messages) {
            try {
                switch (msg.getType()) {
                    case "apply_created":
                        handleApplyCreated(msg);
                        break;
                    // ... 其他消息类型
                }
                msg.setStatus("PROCESSED");
            } catch (Exception e) {
                msg.setRetryCount(msg.getRetryCount() + 1);
                if (msg.getRetryCount() >= 5) {
                    msg.setStatus("FAILED"); // 超过5次进死信
                } else {
                    // 指数退避，下次重试时间
                    msg.setNextRetryTime((int)(System.currentTimeMillis()/1000) + (1 << msg.getRetryCount()) * 60);
                }
            }
            messageRepository.save(msg);
        }
    }

    private void handleApplyCreated(Message msg) {
        JSONObject data = JSON.parseObject(msg.getData());
        Long userId = data.getLong("userId");
        Long jobId = data.getLong("jobId");
        // 调用其他服务（要保证幂等）
        jobService.incrementApplyCount(jobId);
        userService.addPoints(userId, 10);
    }
}
```

**优点**：
- 实现简单，不需要额外的中间件
- 基于本地事务，可靠性高
- 消息和业务数据原子性保证
- 适合大多数最终一致性场景

**缺点**：
- 消息表和业务表在同一个库，耦合
- 扫描消息表有延迟（秒级），不适合实时性要求高的场景
- 消费逻辑要自己写，重试、死信、幂等都要自己处理
- 消息量大时扫描表有性能压力

**适用场景**：大多数最终一致性场景、对实时性要求不高（秒级延迟可接受）、不想引入额外中间件。

---

## 四、方案对比

| 维度 | Saga | TCC | 本地消息表 |
|------|------|-----|-----------|
| 一致性 | 最终一致 | 最终一致（较强） | 最终一致 |
| 隔离性 | 无（中间状态可见） | 有（Try 预留） | 无 |
| 实时性 | 较高（同步调用） | 高（同步调用） | 较低（异步秒级） |
| 开发成本 | 中（要写补偿） | 高（三个接口+幂等） | 低（消息表+扫描） |
| 侵入性 | 中 | 高 | 低 |
| 适用服务数 | 多 | 少（2-3个） | 多 |
| 复杂度 | 中 | 高 | 低 |
| 额外依赖 | 无（或状态机引擎） | 无（或TCC框架） | 无 |

## 五、我们的选型

投递系统的场景：
- 参与服务：apply-service、job-service、user-service，3个服务
- 一致性要求：投递记录要立即创建，职位数和积分可以晚几秒更新
- 实时性：投递记录要实时，其他可以异步
- 开发资源：不想引入太重的框架

**最终选型：本地消息表 + 异步补偿**

- 投递记录在 apply-service 本地事务里创建，同时写消息
- job-service 和 user-service 的更新通过消息异步触发
- 消息消费失败自动重试，超过5次进死信队列人工处理
- 每天跑对账脚本，检查投递数和积分是否一致，不一致自动修复

为什么不选 Saga：投递记录创建后就对外可见了，不需要补偿删除（用户投递了就是投递了，不会因为积分加失败就取消投递）。
为什么不选 TCC：开发成本太高，3个服务要写9个接口，还要处理幂等，投入产出比不高。

## 六、踩坑经验

1. **幂等是必须的**：消息可能重复消费（网络重试、扫描重复），所有消费操作必须幂等。用唯一键（如 user_id + job_id）防重
2. **消息丢失**：本地事务里写消息不会丢，但消费时服务挂了可能没更新状态。用"先处理再更新状态"或"状态机+超时重试"保证不丢
3. **消息积压**：消费速度跟不上生产速度，消息表越来越大。加消费者并发、分表、定期归档已处理消息
4. **对账不能少**：再可靠的方案也可能出问题，定期对账是最后一道防线。每天凌晨跑对账脚本，发现不一致自动修复或告警
5. **不要过度设计**：很多场景本地消息表就够了，没必要上 Seata、TCC 这些重框架。先满足业务需求，再考虑优雅
6. **超时处理**：同步调用其他服务要设置超时，不能无限等待。超时后按失败处理，触发重试或补偿

## 七、总结

分布式事务选型核心：

1. **没有银弹**：Saga、TCC、本地消息表各有适用场景，根据业务需求选
2. **最终一致性是主流**：互联网业务大多选 AP + 最终一致，强一致用得少
3. **本地消息表够用**：80% 的场景本地消息表就能解决，简单可靠，不要过度设计
4. **TCC 用于高一致场景**：支付、库存、金额类对一致性要求高的才用 TCC
5. **Saga 用于长流程**：业务流程长、参与服务多、允许中间状态的用 Saga
6. **幂等+重试+对账**：不管哪种方案，这三个都是必须的，是最终一致性的保障

分布式事务的本质是"在分布式环境下，用工程手段在一致性、可用性、性能之间做权衡"。没有完美的方案，只有最适合业务的方案。选型时先想清楚业务对一致性的真实要求——很多时候"晚几秒一致"完全可以接受，那就用最简单的本地消息表，不要为了技术而技术。
