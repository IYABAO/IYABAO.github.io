---
title: "独立统计数据收集服务设计：异步埋点与数据清洗的工程实践"
date: 2020-09-08T11:20:00+08:00
draft: false
tags: ["数据采集", "架构设计", "异步处理", "Kafka", "数据清洗"]
categories: ["架构设计"]
summary: "独立统计数据收集服务的架构设计与实现，从前端埋点到异步队列、数据清洗、落库存储的完整链路，解决高并发下数据收集不丢不重的问题。"
---

招聘平台的数据分析依赖埋点数据，用户浏览职位、投递简历、查看联系方式等行为都要收集。最早是在业务代码里直接写埋点逻辑，和业务代码耦合在一起，而且同步写库影响接口性能。后来抽出来做了独立的统计数据收集服务，今天把设计和实现过程分享出来。

## 一、背景与问题

原始的埋点方式是在业务接口里直接调用统计方法：

```php
public function actionViewJob($jobId)
{
    // 业务逻辑
    $job = Job::findOne($jobId);
    
    // 埋点：同步写入
    $stat = new JobViewLog();
    $stat->job_id = $jobId;
    $stat->user_id = Yii::$app->user->id;
    $stat->company_id = $job->company_id;
    $stat->ip = Yii::$app->request->userIP;
    $stat->user_agent = Yii::$app->request->userAgent;
    $stat->created_at = time();
    $stat->save();
    
    return $this->asJson(['code' => 0, 'data' => $job]);
}
```

这种方式的问题：

1. **耦合严重**：埋点逻辑散落在各个业务接口里，和业务代码混在一起，维护困难
2. **影响性能**：同步写数据库，增加接口响应时间。高并发时数据库压力大
3. **数据不统一**：不同开发者写的埋点字段不一致，有的多有的少，后续分析困难
4. **扩展性差**：要加新的埋点事件，得改业务代码，重新发布
5. **丢数据风险**：数据库写入失败时，埋点数据就丢了，没有重试机制

## 二、架构设计

独立的统计数据收集服务，核心思路是**异步化 + 标准化**。

### 2.1 整体架构

```text
前端/业务系统 → 埋点SDK → 收集API → Kafka → 清洗服务 → 存储
                                                          ↓
                                                    ClickHouse / MySQL
```

各层职责：
- **埋点 SDK**：前端和后端统一的埋点接口，标准化事件格式
- **收集 API**：接收埋点数据，校验格式，写入 Kafka，立即返回
- **Kafka**：消息队列，解耦收集和处理，削峰填谷
- **清洗服务**：消费 Kafka，数据清洗、去重、补全，写入存储
- **存储**：ClickHouse 存明细数据，MySQL 存聚合结果

### 2.2 设计原则

1. **不丢数据**：至少一次投递（at-least-once），通过幂等去重保证最终一致
2. **不影响业务**：异步处理，埋点失败不影响主流程
3. **标准化**：统一的事件格式，所有埋点事件遵循相同规范
4. **可扩展**：加新事件类型不用改核心代码，配置化
5. **可监控**：全链路监控，数据量、延迟、错误率都能看到

## 三、埋点 SDK 设计

### 3.1 事件格式标准

所有埋点事件统一格式：

```json
{
  "event_id": "evt_20200908123456_abc123",
  "event_type": "job_view",
  "event_time": 1599561296,
  "user_id": 12345,
  "anonymous_id": "anon_abc123",
  "session_id": "sess_def456",
  "platform": "app",
  "app_version": "5.2.0",
  "os": "iOS 14.0",
  "device_id": "device_xyz789",
  "ip": "192.168.1.1",
  "user_agent": "Mozilla/5.0...",
  "properties": {
    "job_id": 67890,
    "company_id": 11111,
    "city_id": 2,
    "source": "search"
  }
}
```

公共字段：
- `event_id`：事件唯一 ID，用于去重
- `event_type`：事件类型，如 job_view、job_apply、interview_invite
- `event_time`：事件发生时间戳
- `user_id`：登录用户 ID，未登录为 null
- `anonymous_id`：匿名 ID，未登录用户标识
- `session_id`：会话 ID
- `platform`：平台（pc/app/miniprogram）
- `properties`：事件特有属性，不同事件类型字段不同

### 3.2 后端 SDK

PHP 后端的埋点 SDK：

```php
class Tracker
{
    private static $kafkaProducer;

    public static function init($brokers)
    {
        self::$kafkaProducer = new \RdKafka\Producer();
        self::$kafkaProducer->addBrokers($brokers);
    }

    public static function track($eventType, $properties = [])
    {
        try {
            $event = [
                'event_id' => self::generateEventId(),
                'event_type' => $eventType,
                'event_time' => time(),
                'user_id' => Yii::$app->user->isGuest ? null : Yii::$app->user->id,
                'anonymous_id' => self::getAnonymousId(),
                'session_id' => self::getSessionId(),
                'platform' => self::detectPlatform(),
                'app_version' => Yii::$app->request->headers->get('App-Version'),
                'os' => Yii::$app->request->headers->get('OS'),
                'device_id' => Yii::$app->request->headers->get('Device-Id'),
                'ip' => Yii::$app->request->userIP,
                'user_agent' => Yii::$app->request->userAgent,
                'properties' => $properties,
            ];

            $topic = self::$kafkaProducer->newTopic('track_events');
            $topic->produce(RD_KAFKA_PARTITION_UA, 0, json_encode($event, JSON_UNESCAPED_UNICODE));
            self::$kafkaProducer->poll(0);
        } catch (Exception $e) {
            // 埋点失败不影响业务，只记日志
            Yii::error('埋点失败: ' . $e->getMessage(), 'tracker');
        }
    }

    private static function generateEventId()
    {
        return 'evt_' . date('YmdHis') . '_' . substr(md5(uniqid(mt_rand(), true)), 0, 8);
    }

    private static function getAnonymousId()
    {
        $id = Yii::$app->request->cookies->getValue('anonymous_id');
        if (!$id) {
            $id = 'anon_' . substr(md5(uniqid(mt_rand(), true)), 0, 16);
            Yii::$app->response->cookies->add(new Cookie([
                'name' => 'anonymous_id',
                'value' => $id,
                'expire' => time() + 86400 * 365 * 2,
            ]));
        }
        return $id;
    }

    private static function detectPlatform()
    {
        $ua = Yii::$app->request->userAgent;
        if (strpos($ua, 'MicroMessenger') !== false) return 'miniprogram';
        if (strpos($ua, 'BestEastApp') !== false) return 'app';
        return 'pc';
    }
}
```

业务代码里调用：

```php
public function actionViewJob($jobId)
{
    $job = Job::findOne($jobId);
    
    // 异步埋点，不影响业务
    Tracker::track('job_view', [
        'job_id' => $jobId,
        'company_id' => $job->company_id,
        'city_id' => $job->city_id,
        'source' => Yii::$app->request->get('source', 'direct'),
    ]);
    
    return $this->asJson(['code' => 0, 'data' => $job]);
}
```

埋点调用写 Kafka，毫秒级返回，不影响业务接口性能。

### 3.3 前端 SDK

前端（JS/小程序/App）也有对应的 SDK，核心逻辑一样：标准化事件格式，异步发送到收集 API。

```javascript
// 前端 JS SDK
class Tracker {
    constructor(config) {
        this.collectUrl = config.collectUrl;
        this.anonymousId = this.getOrCreateAnonymousId();
        this.sessionId = this.getOrCreateSessionId();
        this.queue = [];
        this.flushTimer = null;
    }

    track(eventType, properties = {}) {
        const event = {
            event_id: this.generateEventId(),
            event_type: eventType,
            event_time: Math.floor(Date.now() / 1000),
            user_id: this.getUserId(),
            anonymous_id: this.anonymousId,
            session_id: this.sessionId,
            platform: this.detectPlatform(),
            app_version: this.getAppVersion(),
            device_id: this.getDeviceId(),
            properties: properties,
        };
        
        this.queue.push(event);
        this.scheduleFlush();
    }

    // 批量发送，减少请求数
    scheduleFlush() {
        if (this.flushTimer) return;
        this.flushTimer = setTimeout(() => {
            this.flush();
            this.flushTimer = null;
        }, 1000);
    }

    flush() {
        if (this.queue.length === 0) return;
        const events = this.queue.splice(0);
        navigator.sendBeacon(this.collectUrl, JSON.stringify({ events }));
    }
}
```

前端用 `sendBeacon` 发送，页面关闭时也能发送成功，不丢数据。批量发送，攒 1 秒或满 20 条发一次，减少请求数。

## 四、收集 API

收集 API 是个简单的 HTTP 接口，接收埋点数据，校验格式，写入 Kafka：

```php
class CollectController extends Controller
{
    public $enableCsrfValidation = false;

    public function actionIndex()
    {
        $raw = file_get_contents('php://input');
        $data = json_decode($raw, true);

        if (!$data || !isset($data['events']) || !is_array($data['events'])) {
            return $this->asJson(['code' => 1001, 'message' => '参数错误']);
        }

        $validEvents = [];
        foreach ($data['events'] as $event) {
            if ($this->validateEvent($event)) {
                $validEvents[] = $event;
            }
        }

        if (empty($validEvents)) {
            return $this->asJson(['code' => 1002, 'message' => '无有效事件']);
        }

        // 写入 Kafka
        $producer = Yii::$app->kafka->getProducer();
        $topic = $producer->newTopic('track_events');
        foreach ($validEvents as $event) {
            $topic->produce(RD_KAFKA_PARTITION_UA, 0, json_encode($event, JSON_UNESCAPED_UNICODE));
        }
        $producer->poll(0);

        return $this->asJson(['code' => 0, 'message' => 'success', 'count' => count($validEvents)]);
    }

    private function validateEvent($event)
    {
        $required = ['event_id', 'event_type', 'event_time'];
        foreach ($required as $field) {
            if (!isset($event[$field]) || empty($event[$field])) {
                return false;
            }
        }
        // 事件类型白名单
        $allowedTypes = ['job_view', 'job_apply', 'interview_invite', 'resume_view', 'search', 'click'];
        if (!in_array($event['event_type'], $allowedTypes)) {
            return false;
        }
        return true;
    }
}
```

收集 API 要做到：
- 轻量：只做校验和写 Kafka，不做复杂处理
- 快速：响应时间控制在 10ms 以内
- 容错：Kafka 写入失败时，数据落地到本地文件，后续重放

## 五、数据清洗服务

清洗服务消费 Kafka，做数据清洗、去重、补全，然后写入存储。用 Go 写的，并发处理能力强。

### 5.1 清洗逻辑

```go
func (s *Cleaner) process(event *Event) error {
    // 1. 去重：用 Redis 记录 event_id，已存在则跳过
    if s.duplicate(event.EventID) {
        return nil
    }

    // 2. 数据补全：IP 转地理位置
    if event.IP != "" {
        geo := s.ip2Geo(event.IP)
        event.Country = geo.Country
        event.Province = geo.Province
        event.City = geo.City
    }

    // 3. 数据清洗：User-Agent 解析
    if event.UserAgent != "" {
        ua := s.parseUA(event.UserAgent)
        event.Browser = ua.Browser
        event.OS = ua.OS
        event.Device = ua.Device
    }

    // 4. 字段标准化：时间戳格式统一
    event.EventTime = event.EventTime * 1000 // 转毫秒

    // 5. 写入 ClickHouse
    return s.clickhouse.Write(event)
}

func (s *Cleaner) duplicate(eventID string) bool {
    key := "track:dedup:" + eventID
    result, _ := s.redis.SetNX(key, "1", 86400*7).Result() // 保留7天
    return !result // SetNX 返回 false 表示已存在，是重复数据
}
```

清洗步骤：
1. **去重**：用 Redis 的 SETNX 做幂等，event_id 7天内不重复
2. **IP 转地理位置**：用 IP 库解析出国家、省份、城市
3. **User-Agent 解析**：解析出浏览器、操作系统、设备类型
4. **字段标准化**：统一时间格式、字段命名
5. **写入存储**：明细数据写 ClickHouse

### 5.2 幂等与重试

Kafka 的消费是至少一次投递，可能重复消费。通过 event_id 去重保证最终一致。

处理失败的消息：
- 可重试错误（如 ClickHouse 暂时不可用）：重试 3 次，指数退避
- 不可重试错误（如数据格式错误）：写入死信队列，人工排查

```go
func (s *Cleaner) consume() {
    for {
        msg, err := s.consumer.ReadMessage(context.Background())
        if err != nil {
            log.Printf("消费错误: %v", err)
            continue
        }

        var event Event
        if err := json.Unmarshal(msg.Value, &event); err != nil {
            s.dlq.Write(msg.Value, "格式错误")
            s.consumer.CommitMessage(msg)
            continue
        }

        // 重试处理
        var lastErr error
        for i := 0; i < 3; i++ {
            if err := s.process(&event); err != nil {
                lastErr = err
                time.Sleep(time.Second * time.Duration(1<<i)) // 指数退避
                continue
            }
            lastErr = nil
            break
        }

        if lastErr != nil {
            s.dlq.Write(msg.Value, lastErr.Error())
        }

        s.consumer.CommitMessage(msg) // 处理完提交 offset
    }
}
```

## 六、存储设计

### 6.1 明细数据：ClickHouse

明细数据存 ClickHouse，支持多维分析查询：

```sql
CREATE TABLE track_events (
    event_id String,
    event_type String,
    event_time DateTime64(3),
    user_id Nullable(Int32),
    anonymous_id String,
    session_id String,
    platform String,
    app_version String,
    os String,
    device_id String,
    ip String,
    country String,
    province String,
    city String,
    browser String,
    device String,
    job_id Nullable(Int32),
    company_id Nullable(Int32),
    city_id Nullable(Int32),
    source Nullable(String)
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(event_time)
ORDER BY (event_type, event_time)
TTL event_time + INTERVAL 2 YEAR;
```

事件特有属性（properties）根据事件类型展开成列，不同事件类型的列不同。查询时只查相关列，性能好。

### 6.2 聚合数据：MySQL

常用的聚合结果（如每日 PV/UV、职位浏览量排行）定时计算后存 MySQL，查询更快：

```sql
CREATE TABLE stats_daily_event (
  id int(11) NOT NULL AUTO_INCREMENT,
  date date NOT NULL,
  event_type varchar(50) NOT NULL,
  platform varchar(20) NOT NULL,
  pv int(11) NOT NULL DEFAULT '0',
  uv int(11) NOT NULL DEFAULT '0',
  PRIMARY KEY (`id`),
  UNIQUE KEY `date_type_platform` (`date`,`event_type`,`platform`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

## 七、监控与告警

全链路监控：

1. **收集 API**：QPS、响应时间、错误率、拒绝率
2. **Kafka**：消息堆积量、生产速率、消费速率
3. **清洗服务**：消费延迟、处理成功率、死信队列数量
4. **存储**：ClickHouse 查询延迟、写入速率、磁盘使用率
5. **数据质量**：每日数据量对比、事件类型分布、异常数据告警

告警规则：
- Kafka 堆积 > 10万条，持续 5 分钟 → 告警
- 清洗服务错误率 > 1%，持续 5 分钟 → 告警
- 日数据量环比波动 > 30% → 告警（可能埋点出问题了）
- 死信队列 > 1000 条 → 告警

## 八、踩过的坑

**1. 时钟不同步导致事件时间错乱**

前端和后端服务器时钟不同步，event_time 有的早有的晚，按时间排序时数据错乱。后来统一用服务端接收时间作为 event_time，前端传的时间只做参考。

**2. Kafka 消息太大被拒绝**

有的事件 properties 里塞了太多数据，单条消息超过 1MB，Kafka 拒绝写入。加了消息大小限制，单条不超过 64KB，超过的截断并告警。

**3. 去重 Redis 内存爆了**

event_id 去重保留 7 天，数据量大的时候 Redis 内存涨得很快。后来改成用布隆过滤器（Bloom Filter）做去重，内存占用降了 90%，误判率控制在 0.1% 以内。

**4. 前端 sendBeacon 不支持自定义 header**

用 sendBeacon 发送时不能加自定义 header（如 token），导致无法做鉴权。后来改成收集 API 不鉴权，靠 IP 限流和事件格式校验防刷。

**5. ClickHouse 写入太频繁导致 merge 压力大**

每条事件单独写 ClickHouse，写入 QPS 高，后台 merge 跟不上，部分查询变慢。改成批量写入，攒 1000 条或等 5 秒写一次，写入性能提升 10 倍。

## 九、总结

独立统计数据收集服务的核心设计：

1. **异步化**：埋点写 Kafka，不影响业务接口性能
2. **标准化**：统一事件格式，SDK 封装公共字段，业务方只传事件特有属性
3. **解耦**：收集、清洗、存储分层，各层独立扩展
4. **幂等**：event_id 去重，至少一次投递 + 幂等 = 最终一致
5. **容错**：失败重试 + 死信队列，不丢数据
6. **监控**：全链路监控，数据质量告警，出问题早发现

这套服务上线后，埋点数据的收集和处理不再影响业务系统，数据质量也大幅提升。后续加新的埋点事件，只需要在 SDK 里调用 `track()`，不用改业务代码，扩展性很好。

数据收集是数据分析的基础，数据质量决定了分析结果的可信度。花时间把数据收集的管道搭好，后续的数据分析和业务决策才有可靠的依据。
