---
title: "招聘通 PC 5.0 架构升级：前后端分离与接口标准化实践"
date: 2021-07-18T11:00:00+08:00
draft: false
tags: ["架构升级", "前后端分离", "API设计", "PHP", "Yii2", "Vue"]
categories: ["架构设计"]
summary: "招聘通 PC 端从服务端渲染到前后端分离的架构升级实践，涵盖 API 标准化、鉴权方案、接口文档自动化、前端工程化，以及迁移过程中的踩坑经验。"
---

招聘通 PC 端最早是 Yii2 服务端渲染（Server-Side Rendering），PHP 直接输出 HTML。随着功能越来越复杂，前端交互越来越多，服务端渲染的模式越来越吃力——前后端代码混在一起，改个样式要动 PHP 文件，前端框架用不起来。2021年中做了 PC 5.0 架构升级，全面转向前后端分离，今天把实践经验分享出来。

## 一、为什么要升级

服务端渲染的痛点：

1. **前后端耦合**：PHP 模板里混着 HTML、JS、CSS，前端工程师改代码要懂 PHP
2. **交互能力弱**：复杂交互（如拖拽、实时搜索、表单联动）实现困难，代码臃肿
3. **性能差**：每次页面切换都要服务端渲染完整 HTML，白屏时间长
4. **复用性差**：PC 和 App 端的业务逻辑重复实现，无法共享
5. **技术栈老旧**：用的还是 jQuery + Bootstrap，前端生态的新东西用不了

## 二、架构设计

### 2.1 整体架构

```text
浏览器（Vue SPA） → Nginx → 后端 API（Yii2 RESTful）
                          ↓
                    MySQL / Redis / Elasticsearch
```

- **前端**：Vue 2 + Vue Router + Vuex + Element UI，SPA 单页应用
- **后端**：Yii2 改造为纯 API 服务，只输出 JSON，不渲染 HTML
- **部署**：前端静态资源部署到 CDN，API 服务独立部署
- **鉴权**：JWT Token，前端存在 localStorage，每次请求带 Authorization 头

### 2.2 API 标准化

统一的 API 规范，所有接口遵循相同的格式：

**请求规范：**
- RESTful 风格：GET 查询、POST 创建、PUT 更新、DELETE 删除
- URL 用名词复数：`/jobs`、`/resumes`、`/companies`
- 分页参数：`page`、`page_size`
- 排序参数：`sort`、`order`
- 过滤参数：直接用字段名，如 `status=1&city_id=2`

**响应规范：**
```json
{
  "code": 0,
  "message": "success",
  "data": {},
  "request_id": "req_20210718_abc123"
}
```

- `code`：0 表示成功，非 0 表示错误
- `message`：错误信息，成功时为 "success"
- `data`：业务数据
- `request_id`：请求唯一标识，用于排查问题

**分页响应：**
```json
{
  "code": 0,
  "message": "success",
  "data": {
    "list": [],
    "total": 100,
    "page": 1,
    "page_size": 20
  }
}
```

**错误码规范：**
- 0-999：系统级错误（0成功，1参数错误，2未登录，3无权限，4服务器错误）
- 1000-1999：用户模块
- 2000-2999：职位模块
- 3000-3999：简历模块
- 4000-4999：企业模块

### 2.3 统一响应处理

Yii2 里用 Response 行为统一格式化响应：

```php
class ApiResponseBehavior extends Behavior
{
    public function events()
    {
        return [
            Controller::EVENT_AFTER_ACTION => 'afterAction',
        ];
    }

    public function afterAction($event)
    {
        $response = Yii::$app->response;
        $data = $event->result;

        // 如果已经是标准格式，直接返回
        if (is_array($data) && isset($data['code'])) {
            $response->data = $data;
            return;
        }

        // 包装成标准格式
        $response->data = [
            'code' => 0,
            'message' => 'success',
            'data' => $data,
            'request_id' => Yii::$app->requestId,
        ];
    }
}
```

Controller 里直接 return 数据，不用手动包装：

```php
public function actionView($id)
{
    $job = Job::findOne($id);
    if (!$job) {
        throw new NotFoundHttpException('职位不存在');
    }
    return $job->toArray();
}
```

### 2.4 异常处理

统一异常处理，把异常转成标准错误响应：

```php
class ErrorHandler extends \yii\web\ErrorHandler
{
    protected function renderException($exception)
    {
        $response = Yii::$app->response;
        $response->format = Response::FORMAT_JSON;

        if ($exception instanceof UnauthorizedHttpException) {
            $response->statusCode = 401;
            $code = 2;
        } elseif ($exception instanceof ForbiddenHttpException) {
            $response->statusCode = 403;
            $code = 3;
        } elseif ($exception instanceof NotFoundHttpException) {
            $response->statusCode = 404;
            $code = 404;
        } elseif ($exception instanceof BadRequestHttpException) {
            $response->statusCode = 400;
            $code = 1;
        } else {
            $response->statusCode = 500;
            $code = 500;
            Yii::error($exception); // 记录错误日志
        }

        $response->data = [
            'code' => $code,
            'message' => $exception->getMessage(),
            'data' => null,
            'request_id' => Yii::$app->requestId,
        ];
    }
}
```

### 2.5 JWT 鉴权

```php
class JwtAuthBehavior extends Behavior
{
    public function events()
    {
        return [
            Controller::EVENT_BEFORE_ACTION => 'beforeAction',
        ];
    }

    public function beforeAction($event)
    {
        $action = $event->action->id;
        // 白名单接口不需要登录
        if (in_array($action, $this->whiteList)) {
            return true;
        }

        $token = Yii::$app->request->headers->get('Authorization');
        if (!$token || !preg_match('/^Bearer\s+(.*)$/', $token, $matches)) {
            throw new UnauthorizedHttpException('请先登录');
        }

        try {
            $payload = JWT::decode($matches[1], $this->secret, ['HS256']);
            $user = User::findOne($payload->uid);
            if (!$user || $user->status != 1) {
                throw new UnauthorizedHttpException('账号不存在或已禁用');
            }
            Yii::$app->user->setIdentity($user);
        } catch (Exception $e) {
            throw new UnauthorizedHttpException('登录已过期，请重新登录');
        }

        return true;
    }
}
```

## 三、前端工程化

### 3.1 技术栈

- 框架：Vue 2.6
- 路由：Vue Router
- 状态管理：Vuex
- UI 组件库：Element UI
- HTTP 客户端：Axios
- 构建工具：Vue CLI（Webpack）
- 代码规范：ESLint + Prettier

### 3.2 项目结构

```text
src/
  api/          # API 接口封装
  assets/       # 静态资源
  components/   # 公共组件
  layouts/      # 布局组件
  router/       # 路由配置
  store/        # Vuex 状态管理
  utils/        # 工具函数
  views/        # 页面组件
  App.vue
  main.js
```

### 3.3 API 封装

Axios 封装统一的请求拦截和响应处理：

```javascript
// utils/request.js
import axios from 'axios'
import store from '@/store'
import router from '@/router'

const service = axios.create({
  baseURL: process.env.VUE_APP_API_BASE_URL,
  timeout: 15000
})

// 请求拦截：加 Token
service.interceptors.request.use(
  config => {
    const token = store.getters.token
    if (token) {
      config.headers['Authorization'] = `Bearer ${token}`
    }
    return config
  },
  error => Promise.reject(error)
)

// 响应拦截：统一处理错误
service.interceptors.response.use(
  response => {
    const res = response.data
    if (res.code !== 0) {
      // 处理错误
      if (res.code === 2) {
        // 未登录，跳登录页
        store.dispatch('user/logout')
        router.push('/login')
      }
      return Promise.reject(new Error(res.message || '请求失败'))
    }
    return res.data
  },
  error => {
    return Promise.reject(error)
  }
)

export default service
```

API 模块化：

```javascript
// api/job.js
import request from '@/utils/request'

export function getJobList(params) {
  return request({
    url: '/jobs',
    method: 'get',
    params
  })
}

export function getJobDetail(id) {
  return request({
    url: `/jobs/${id}`,
    method: 'get'
  })
}

export function createJob(data) {
  return request({
    url: '/jobs',
    method: 'post',
    data
  })
}

export function updateJob(id, data) {
  return request({
    url: `/jobs/${id}`,
    method: 'put',
    data
  })
}
```

### 3.4 接口文档自动化

后端用 Swagger 自动生成 API 文档，前端根据文档生成 API 调用代码，减少手写错误。

Yii2 配置 Swagger：

```php
// 用 yii2-swagger 扩展
public function actions()
{
    return [
        'doc' => [
            'class' => 'light\swagger\SwaggerAction',
            'restUrl' => '/api/site/api',
        ],
        'api' => [
            'class' => 'light\swagger\SwaggerApiAction',
            'scanDir' => [
                '@app/modules/api/controllers',
                '@app/modules/api/models',
            ],
        ],
    ];
}
```

Controller 里用注解描述接口：

```php
/**
 * @SWG\Get(
 *   path="/jobs",
 *   summary="职位列表",
 *   @SWG\Parameter(name="page", in="query", type="integer", default=1),
 *   @SWG\Parameter(name="page_size", in="query", type="integer", default=20),
 *   @SWG\Response(response="200", description="成功")
 * )
 */
public function actionIndex()
{
    // ...
}
```

## 四、迁移策略

老系统不能一下全换掉，用渐进式迁移：

1. **新功能用新架构**：新增功能全部用 Vue + API 的方式开发
2. **老功能逐步迁移**：按模块优先级，逐个把老页面重构成 Vue
3. **共存期**：Nginx 根据路径分流，老路径走 PHP 渲染，新路径走 Vue SPA
4. **下线老代码**：所有模块迁移完成后，下线老的服务端渲染代码

Nginx 配置：

```nginx
# 老页面走 PHP
location ~ ^/(old-page|legacy)/ {
    fastcgi_pass unix:/run/php/php7.4-fpm.sock;
    # ...
}

# 新页面走 Vue
location / {
    try_files $uri $uri/ /index.html;
}

# API 走后端
location /api/ {
    fastcgi_pass unix:/run/php/php7.4-fpm.sock;
    # ...
}
```

## 五、踩过的坑

**1. SPA 路由刷新 404**

Vue Router 用 history 模式，刷新页面时 Nginx 找不到对应文件返回 404。解决：Nginx 配置 `try_files $uri $uri/ /index.html;`，所有路径都指向 index.html，由前端路由处理。

**2. 跨域问题**

前后端分离后，前端和 API 不同域名，出现跨域问题。后端配置 CORS：

```php
public function behaviors()
{
    return [
        'corsFilter' => [
            'class' => \yii\filters\Cors::className(),
            'cors' => [
                'Origin' => ['https://pc.example.com'],
                'Access-Control-Request-Method' => ['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'],
                'Access-Control-Request-Headers' => ['*'],
                'Access-Control-Allow-Credentials' => true,
            ],
        ],
    ];
}
```

或者用 Nginx 反向代理，前端和 API 同域名，避免跨域。

**3. Token 过期处理**

JWT Token 过期后，API 返回 401，前端要处理跳登录页。但如果同时发多个请求，会多次跳登录页。用请求队列，401 时暂停所有请求，跳登录页后再恢复。

**4. 首屏白屏**

SPA 首屏需要加载 JS 后才渲染，白屏时间长。优化：路由懒加载、JS/CSS 压缩、CDN 加速、加 loading 动画、关键页面做 SSR 或预渲染。

**5. SEO 问题**

SPA 对 SEO 不友好，搜索引擎爬不到内容。招聘通的职位详情页需要 SEO，后来对职位详情页做了服务端渲染（或预渲染），其他页面保持 SPA。

## 六、效果

升级前后对比：

| 指标 | 服务端渲染 | 前后端分离 | 提升 |
|------|-----------|-----------|------|
| 页面切换速度 | 800ms（整页刷新） | 100ms（局部更新） | 87%↓ |
| 首屏加载 | 500ms | 800ms（白屏） | 稍慢（优化后600ms） |
| 前端开发效率 | 低（要懂PHP） | 高（纯前端） | 显著提升 |
| 代码复用 | 低 | 高（API 共享） | 显著提升 |
| 线上问题定位 | 困难 | 清晰（request_id） | 显著提升 |

## 七、总结

招聘通 PC 5.0 前后端分离升级的核心经验：

1. **API 标准化**：统一的请求/响应格式、错误码、分页规范，是前后端协作的基础
2. **鉴权方案**：JWT Token + 请求拦截，统一处理登录态和过期
3. **前端工程化**：模块化 API 封装、统一错误处理、代码规范，提升开发效率
4. **接口文档自动化**：Swagger 注解自动生成文档，减少前后端沟通成本
5. **渐进式迁移**：新功能用新架构，老功能逐步迁移，共存期用 Nginx 分流
6. **注意坑点**：SPA 路由 404、跨域、Token 过期、首屏白屏、SEO，这些都要提前考虑

前后端分离不是银弹，它提升了开发效率和交互体验，但也带来了首屏白屏、SEO 等新问题。要根据业务场景选择，不是所有项目都适合前后端分离。对招聘通这种交互复杂、前端功能多的系统，前后端分离是正确的选择。
