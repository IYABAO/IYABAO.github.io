---
title: "企业小程序全栈开发实践：Yii2.0 + 阿里云 + MySQL 的闭环搭建"
date: 2019-11-05T11:30:00+08:00
draft: false
tags: ["PHP", "Yii2", "微信小程序", "阿里云", "MySQL"]
categories: ["PHP开发"]
summary: "企业招聘小程序从0到1的全栈开发实践，后端基于 Yii2.0 搭建，部署在阿里云，涵盖登录授权、简历管理、职位投递等核心功能的完整实现。"
---

2019年做了个企业招聘小程序，客户是酒店行业的招聘平台，需要在微信小程序里完成企业注册、职位发布、简历投递、面试邀约等完整招聘流程。后端用 Yii2.0 搭的，部署在阿里云 ECS 上。今天把这个项目的全栈开发实践整理出来。

## 一、项目背景与技术选型

客户需求很明确：
- 企业端：注册登录、职位发布管理、简历查看、面试邀约
- 求职者端：简历填写、职位搜索、投递记录、消息通知
- 管理后台：数据统计、内容审核、企业管理

技术选型：
- 后端：Yii2.0（团队熟悉，开发效率高）
- 数据库：MySQL 5.7
- 缓存：Redis
- 部署：阿里云 ECS + RDS + OSS
- 小程序：微信原生开发

为什么选 Yii2.0？团队之前一直用 Yii，开发效率高，Gii 代码生成器能快速生成 CRUD，ActiveRecord 用起来顺手。小项目快速迭代，Yii2 是很合适的选择。

## 二、后端架构设计

### 2.1 目录结构

```
api/                    # 小程序 API
  controllers/
    v1/
      AuthController.php
      JobController.php
      ResumeController.php
      CompanyController.php
  models/
  services/
admin/                  # 管理后台
  controllers/
  views/
common/                 # 公共代码
  models/
  services/
  helpers/
console/                # 命令行脚本
  controllers/
config/                 # 配置文件
web/                    # 入口文件
```

API 和后台分开部署，API 走 `api.example.com`，后台走 `admin.example.com`。公共模型和服务放在 `common` 目录，两边共享。

### 2.2 模块化设计

按业务领域划分模块：
- `Auth`：登录授权、Token 管理
- `Company`：企业注册、信息管理
- `Job`：职位发布、搜索、管理
- `Resume`：简历创建、投递、管理
- `Message`：消息通知、面试邀约
- `File`：文件上传（头像、简历附件）

每个模块有独立的 Controller、Model、Service，Service 层封装业务逻辑，Controller 只做参数校验和响应格式化。

### 2.3 API 响应格式

统一的响应格式，前端处理起来方便：

```php
// 成功响应
return [
    'code' => 0,
    'message' => 'success',
    'data' => $data,
];

// 错误响应
return [
    'code' => 1001,
    'message' => '参数错误',
    'data' => null,
];
```

用 Yii2 的 `beforeAction` 和 `afterAction` 做统一的响应格式化和异常处理：

```php
public function behaviors()
{
    return [
        'contentNegotiator' => [
            'class' => ContentNegotiator::className(),
            'formats' => [
                'application/json' => Response::FORMAT_JSON,
            ],
        ],
    ];
}
```

## 三、核心功能实现

### 3.1 小程序登录授权

微信小程序登录走 `code2session` 接口，用 code 换 openid 和 session_key。我们的方案是后端生成自定义 Token，存在 Redis 里，前端每次请求带 Token。

```php
class AuthController extends Controller
{
    public function actionLogin()
    {
        $code = Yii::$app->request->post('code');
        if (!$code) {
            return ['code' => 1001, 'message' => 'code不能为空'];
        }

        // 调用微信接口换 openid
        $wechat = new WechatMiniProgram();
        $session = $wechat->code2Session($code);
        $openid = $session['openid'];

        // 查找或创建用户
        $user = User::findOne(['openid' => $openid]);
        if (!$user) {
            $user = new User();
            $user->openid = $openid;
            $user->created_at = time();
            $user->save();
        }

        // 生成 Token
        $token = $this->generateToken($user->id);
        $redis = Yii::$app->redis;
        $redis->setex("user_token:{$token}", 86400 * 30, $user->id);

        return [
            'code' => 0,
            'message' => 'success',
            'data' => [
                'token' => $token,
                'user_info' => [
                    'id' => $user->id,
                    'nickname' => $user->nickname,
                    'avatar' => $user->avatar,
                ],
            ],
        ];
    }

    private function generateToken($userId)
    {
        return md5($userId . time() . Yii::$app->security->generateRandomString(16));
    }
}
```

Token 验证用行为（Behavior）实现：

```php
class TokenAuthBehavior extends Behavior
{
    public function events()
    {
        return [
            Controller::EVENT_BEFORE_ACTION => 'beforeAction',
        ];
    }

    public function beforeAction($event)
    {
        $token = Yii::$app->request->getHeaders()->get('Authorization');
        if (!$token) {
            throw new UnauthorizedHttpException('未登录');
        }

        $userId = Yii::$app->redis->get("user_token:{$token}");
        if (!$userId) {
            throw new UnauthorizedHttpException('登录已过期');
        }

        Yii::$app->user->setIdentity(User::findOne($userId));
        return true;
    }
}
```

### 3.2 职位搜索

职位搜索是核心功能，需要支持关键词、城市、薪资、经验、学历等多维度筛选。数据量不大的时候用 MySQL 就行，加好联合索引：

```sql
CREATE TABLE `job` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `company_id` int(11) NOT NULL,
  `title` varchar(100) NOT NULL,
  `city_id` int(11) NOT NULL,
  `salary_min` int(11) NOT NULL,
  `salary_max` int(11) NOT NULL,
  `experience` varchar(20) DEFAULT NULL,
  `education` varchar(20) DEFAULT NULL,
  `status` tinyint(1) NOT NULL DEFAULT '1',
  `created_at` int(11) NOT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_city_status_created` (`city_id`,`status`,`created_at`),
  KEY `idx_company_status` (`company_id`,`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

搜索接口：

```php
public function actionSearch()
{
    $keyword = Yii::$app->request->get('keyword', '');
    $cityId = Yii::$app->request->get('city_id', 0);
    $salaryMin = Yii::$app->request->get('salary_min', 0);
    $salaryMax = Yii::$app->request->get('salary_max', 0);
    $experience = Yii::$app->request->get('experience', '');
    $page = Yii::$app->request->get('page', 1);
    $pageSize = Yii::$app->request->get('page_size', 20);

    $query = Job::find()
        ->where(['status' => 1])
        ->orderBy(['created_at' => SORT_DESC]);

    if ($keyword) {
        $query->andWhere(['like', 'title', $keyword]);
    }
    if ($cityId) {
        $query->andWhere(['city_id' => $cityId]);
    }
    if ($salaryMin) {
        $query->andWhere(['>=', 'salary_max', $salaryMin]);
    }
    if ($salaryMax) {
        $query->andWhere(['<=', 'salary_min', $salaryMax]);
    }
    if ($experience) {
        $query->andWhere(['experience' => $experience]);
    }

    $count = $query->count();
    $list = $query
        ->offset(($page - 1) * $pageSize)
        ->limit($pageSize)
        ->with('company')
        ->asArray()
        ->all();

    return [
        'code' => 0,
        'data' => [
            'list' => $list,
            'total' => $count,
            'page' => $page,
            'page_size' => $pageSize,
        ],
    ];
}
```

关键词搜索用 `LIKE` 在数据量小的时候够用，数据量大了之后要换 Elasticsearch。我们这个项目职位数在 5 万以内，MySQL 完全够用。

### 3.3 简历投递

简历投递要防重复投递，同一个用户对同一个职位只能投递一次。用数据库唯一索引 + Redis 分布式锁双重保障：

```sql
ALTER TABLE `job_apply` ADD UNIQUE KEY `uk_user_job` (`user_id`,`job_id`);
```

```php
public function actionApply()
{
    $jobId = Yii::$app->request->post('job_id');
    $userId = Yii::$app->user->id;

    // Redis 防重
    $lockKey = "apply_lock:{$userId}:{$jobId}";
    if (!Yii::$app->redis->set($lockKey, 1, 'NX', 'EX', 5)) {
        return ['code' => 2001, 'message' => '请勿重复投递'];
    }

    try {
        $apply = new JobApply();
        $apply->user_id = $userId;
        $apply->job_id = $jobId;
        $apply->resume_id = Yii::$app->request->post('resume_id');
        $apply->status = 1; // 已投递
        $apply->created_at = time();

        if (!$apply->save()) {
            // 唯一索引冲突
            if (strpos($apply->getFirstError(''), 'Duplicate') !== false) {
                return ['code' => 2002, 'message' => '已经投递过该职位'];
            }
            return ['code' => 2003, 'message' => '投递失败'];
        }

        // 投递成功，发通知给企业
        Yii::$app->queue->push(new NewApplyJob([
            'apply_id' => $apply->id,
        ]));

        return ['code' => 0, 'message' => '投递成功'];
    } finally {
        Yii::$app->redis->del($lockKey);
    }
}
```

Redis 锁防止用户快速点击重复提交，数据库唯一索引保证最终一致性。两层防护，万无一失。

### 3.4 文件上传

头像和简历附件上传到阿里云 OSS，用 STS 临时授权让前端直传，后端只负责生成 STS Token：

```php
public function actionSts()
{
    $oss = new AliyunOSS();
    $sts = $oss->generateStsToken([
        'bucket' => 'recruit-files',
        'dir' => 'uploads/' . date('Ymd') . '/',
        'expire' => 3600,
    ]);

    return [
        'code' => 0,
        'data' => $sts,
    ];
}
```

前端拿到 STS Token 后直接上传到 OSS，上传成功后把 URL 传给后端保存。这样做的好处是文件流量不经过服务器，节省带宽，上传速度也更快。

## 四、部署与运维

### 4.1 阿里云架构

```
用户 → SLB 负载均衡 → ECS（API + 后台）
                           ↓
                         RDS MySQL
                         Redis
                         OSS（文件存储）
```

SLB 做负载均衡，后面挂两台 ECS，RDS 用高可用版，Redis 用主从版。OSS 存文件，CDN 加速静态资源。

### 4.2 自动化部署

用 GitLab CI 做自动化部署，代码 push 到 master 分支后自动构建部署：

```yaml
stages:
  - test
  - deploy

test:
  stage: test
  script:
    - composer install
    - ./vendor/bin/phpunit

deploy_production:
  stage: deploy
  only:
    - master
  script:
    - ssh deploy@api.example.com "cd /var/www/api && git pull && composer install --no-dev && php yii migrate --interactive=0"
```

数据库迁移用 Yii2 的 Migration，每次发布自动执行，不用手动改数据库。

### 4.3 监控告警

- 服务器监控：阿里云云监控，CPU、内存、磁盘告警
- 应用监控：自己写了个健康检查接口，定时访问，异常告警
- 错误日志：Yii2 的日志写到文件，用 Logtail 采集到阿里云 SLS，错误率超阈值告警
- 业务监控：投递量、注册量等核心指标，每天出报表

## 五、踩过的坑

**1. 微信 code 只能用一次**

`code2session` 的 code 只能用一次，用完就失效。前端如果重复调用登录接口，第二次会失败。要做好前端控制，登录中禁用按钮。

**2. OSS STS 权限最小化**

STS Token 的权限要最小化，只允许上传到指定目录，不允许删除和下载。否则 Token 泄露后别人可以操作你的 OSS。

**3. 小程序审核**

微信小程序审核很严，招聘类小程序需要提供人力资源服务许可证。提前准备好资质，否则审核会被拒，耽误上线时间。

**4. 并发投递**

上线初期没加 Redis 锁，只靠数据库唯一索引。遇到过用户快速点击投递按钮，请求同时到达，都通过了"是否已投递"的检查，然后同时插入，其中一个报唯一索引冲突返回错误。用户体验不好，后来加了 Redis 锁解决。

**5. 图片压缩**

小程序上传图片如果不压缩，一张几 MB，上传慢还占存储空间。前端上传前要压缩，后端也可以再加一层压缩。我们用了阿里云 OSS 的图片处理服务，实时压缩，不用自己处理。

## 六、总结

这个企业招聘小程序从 0 到 1 上线，用了大概 2 个月时间。后端 Yii2.0 开发效率确实高，Gii 生成 CRUD，ActiveRecord 操作数据库，Validation 做参数校验，这些基础功能都很成熟，开发者可以专注在业务逻辑上。

核心经验：
1. 小程序登录用自定义 Token + Redis，比微信 session_key 更灵活
2. 防重复提交要 Redis 锁 + 数据库唯一索引双重保障
3. 文件上传用 OSS STS 直传，省带宽省服务器资源
4. 自动化部署 + 数据库迁移，减少人为操作失误
5. 监控告警要提前搭好，上线后才能快速发现问题

这个项目后来迭代了很多功能，视频面试、在线笔试、AI 简历解析等等，基础架构一直没动，说明当初的架构设计是合理的。技术选型没有最好的，只有最合适的。对这个项目来说，Yii2.0 + 阿里云就是最合适的组合。
