---
title: "高峰论坛活动系统架构：高并发活动页的缓存与降级策略"
date: 2022-12-05T15:00:00+08:00
draft: false
tags: ["高并发", "缓存", "降级", "活动系统", "PHP", "Redis"]
categories: ["架构设计"]
summary: "招聘平台高峰论坛活动系统架构设计，高并发场景下的多级缓存策略、限流降级方案、静态化处理，支撑活动当天 10 倍流量峰值稳定运行。"
---

每年最佳东方高峰论坛是平台的大活动，活动当天流量是平时的 5-10 倍，活动页、报名页、直播页都要扛住高并发。2022年高峰论坛活动系统做了专门的架构设计，今天把高并发下的缓存与降级策略分享出来。

## 一、流量预估与挑战

- 活动当天 UV 50万+，PV 300万+
- 峰值 QPS 5000+（活动开始前 10 分钟和直播开始时）
- 核心页面：活动首页、报名页、议程页、直播页
- 挑战：瞬时流量大、报名操作有写操作、直播页有实时数据

## 二、多级缓存策略

### 2.1 页面静态化

活动首页、议程页等内容不常变的页面，提前生成静态 HTML，放 CDN：

```php
// 生成静态页面
$html = $this->renderActivityPage($activityId);
file_put_contents("/data/static/activity_{$activityId}.html", $html);

// 上传到 OSS + CDN
$this->oss->upload("static/activity_{$activityId}.html", $html);
```

用户访问 CDN 静态页，完全不经过源站，QPS 再高也不怕。

### 2.2 Redis 缓存

需要动态数据的页面（如报名人数、实时观看人数），用 Redis 缓存：

```php
public function getActivityInfo($activityId)
{
    $cacheKey = "activity:info:{$activityId}";
    $cached = Yii::$app->redis->get($cacheKey);
    if ($cached !== false) {
        return json_decode($cached, true);
    }

    // 缓存击穿保护：分布式锁
    $lockKey = "activity:lock:{$activityId}";
    if (!Yii::$app->redis->set($lockKey, 1, 'NX', 'EX', 5)) {
        usleep(100000); // 等100ms重试
        return $this->getActivityInfo($activityId);
    }

    try {
        $info = $this->queryFromDb($activityId);
        Yii::$app->redis->setex($cacheKey, 300, json_encode($info)); // 5分钟
        return $info;
    } finally {
        Yii::$app->redis->del($lockKey);
    }
}
```

### 2.3 本地缓存

热点数据用 APCu 本地缓存，减少 Redis 访问：

```php
public function getHotActivity()
{
    $local = apcu_fetch('activity:hot');
    if ($local !== false) return $local;

    $redis = Yii::$app->redis->get('activity:hot');
    if ($redis !== false) {
        $data = json_decode($redis, true);
        apcu_store('activity:hot', $data, 60); // 本地缓存1分钟
        return $data;
    }

    $data = $this->queryFromDb();
    Yii::$app->redis->setex('activity:hot', 300, json_encode($data));
    apcu_store('activity:hot', $data, 60);
    return $data;
}
```

三级缓存：CDN/静态页 → 本地缓存 → Redis → 数据库，越靠后访问越少。

## 三、限流与降级

### 3.1 接口限流

用 Redis 令牌桶限流：

```php
public function checkRateLimit($key, $limit, $window = 60)
{
    $redis = Yii::$app->redis;
    $current = $redis->incr("rate:{$key}");
    if ($current == 1) {
        $redis->expire("rate:{$key}", $window);
    }
    if ($current > $limit) {
        throw new TooManyRequestsException('请求过于频繁，请稍后再试');
    }
    return true;
}

// 报名接口限流：每分钟每用户最多5次
$this->checkRateLimit("signup:{$userId}", 5);
```

### 3.2 服务降级

活动高峰期，非核心功能降级：

```php
public function actionActivityIndex($activityId)
{
    $data = [];
    
    // 核心功能：活动信息
    $data['info'] = $this->getActivityInfo($activityId);
    
    // 非核心：推荐活动（失败不影响主流程）
    try {
        $data['recommend'] = $this->getRecommendActivities();
    } catch (Exception $e) {
        $data['recommend'] = []; // 降级返回空
    }
    
    // 非核心：实时聊天（高峰期关闭）
    if (!$this->isHighTraffic()) {
        $data['chat'] = $this->getRecentChat($activityId);
    } else {
        $data['chat'] = ['status' => 'closed', 'msg' => '高峰期聊天功能暂不可用'];
    }
    
    return $data;
}
```

降级策略：
- 推荐活动：失败返回空
- 实时聊天：高峰期直接关闭
- 报名统计：显示近似值（缓存数据），不实时查
- 个人中心：高峰期隐藏非必要模块

### 3.3 报名操作优化

报名是写操作，不能纯缓存。用异步队列削峰：

```php
public function actionSignup($activityId)
{
    $userId = Yii::$app->user->id;
    
    // 幂等检查
    if (Yii::$app->redis->sismember("signup:{$activityId}", $userId)) {
        return ['code' => 0, 'message' => '已报名'];
    }
    
    // 异步报名
    Yii::$app->queue->push(new SignupJob([
        'activity_id' => $activityId,
        'user_id' => $userId,
    ]));
    
    // 立即返回，后台异步处理
    return ['code' => 0, 'message' => '报名成功，正在处理中'];
}
```

报名请求立即返回，后台异步处理写数据库。用户体验好，数据库压力小。

## 四、压测与预案

### 4.1 压测

活动前用 JMeter 压测，模拟峰值流量：

```bash
# 压测活动首页，5000并发
jmeter -n -t activity_test.jmx -Jthreads=5000 -Jduration=300
```

压测发现的问题：
- 数据库连接池不够 → 调大连接池
- Redis 连接数不够 → 调大 maxclients
- 某个接口没缓存 → 加缓存

### 4.2 应急预案

- **CDN 故障**：切换到备用 CDN 或源站
- **Redis 故障**：降级到数据库（限流保护）
- **数据库故障**：只读模式，暂停报名等写操作
- 服务器扩容：提前准备好扩容脚本，5分钟内能加机器

## 五、效果

活动当天数据：
- 峰值 QPS 6200，系统稳定运行
- 活动首页响应时间 < 50ms（CDN 静态页）
- 报名接口响应时间 < 100ms（异步队列）
- 数据库 QPS 峰值 800（平时 200，缓存扛了大部分）
- 0 宕机，0 数据丢失

## 六、总结

高并发活动系统的核心经验：

1. **能静态就静态**：活动页提前生成静态 HTML 放 CDN，源站压力最小
2. **多级缓存**：CDN → 本地缓存 → Redis → 数据库，层层拦截
3. **异步削峰**：写操作用消息队列异步处理，请求立即返回
4. **限流保护**：核心接口限流，防止被打垮
5. **降级预案**：非核心功能高峰期降级，保证核心功能可用
6. **压测验证**：活动前充分压测，发现问题提前修复
7. **应急预案**：各种故障场景都有预案，出问题能快速恢复

高并发系统的设计思路是"能不查数据库就不查，能异步就异步，能降级就降级"。核心功能保证可用，非核心功能该砍就砍。活动系统不是日常系统，不需要所有功能都可用，高峰期保住核心功能就行。
