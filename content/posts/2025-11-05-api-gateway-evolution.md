---
title: "API 网关演进：从 Kong 到 APISIX 的云原生网关选型实践"
date: 2025-11-05T10:00:00+08:00
draft: false
tags: ["API网关", "Kong", "APISIX", "云原生", "微服务", "流量治理"]
categories: ["架构设计"]
summary: "API 网关从 Kong 到 APISIX 的演进实践，涵盖网关选型对比、迁移方案、性能压测、插件开发、流量治理，以及在招聘平台微服务架构中的落地经验和踩坑记录。"
---

API 网关是微服务架构的入口，所有流量都经过它，性能和稳定性至关重要。我们最早用 Nginx + Lua 自己写网关，后来换成 Kong，2025年又迁移到了 APISIX。今天把网关演进的完整过程、选型对比、迁移实践分享出来。

## 一、为什么需要 API 网关

微服务拆分后，前端不能直接调用每个后端服务，需要一个统一入口：

1. **路由转发**：根据 URL 路径路由到不同的后端服务
2. **统一鉴权**：JWT/OAuth/API Key 校验，不用每个服务都实现
3. **限流熔断**：保护后端服务不被打垮
4. **日志监控**：统一采集访问日志、指标、追踪
5. **协议转换**：HTTP ↔ gRPC、REST ↔ GraphQL
6. **缓存**：静态资源和接口响应缓存
7. **灰度发布**：按比例/用户特征路由到不同版本

这些是横切关注点，放在网关里统一处理，后端服务只关注业务逻辑。

## 二、三代网关演进

### 第一代：Nginx + Lua（自研）

最早用 Nginx + OpenResty（Lua）自己写网关：

```nginx
location /api/resume/ {
    access_by_lua_block {
        -- 鉴权
        local token = ngx.var.http_authorization
        if not validate_token(token) then
            ngx.exit(401)
        end
        -- 限流
        if not rate_limit(ngx.var.remote_addr) then
            ngx.exit(429)
        end
    }
    proxy_pass http://resume_service;
}
```

**优点**：
- 灵活，想怎么写怎么写
- 性能好，Nginx 本身很强
- 成本低，不用额外组件

**缺点**：
- 维护成本高，所有插件都要自己写
- 配置热更新麻烦，改 Lua 要 reload
- 没有管理界面，配置管理靠文件和脚本
- 团队人员流动后，Lua 代码没人敢改
- 动态路由、限流规则变更不灵活

用了两年，随着服务数量增长（20+ 服务），自研网关的维护成本越来越高，决定换成成熟的网关产品。

---

### 第二代：Kong

Kong 是基于 OpenResty 的开源 API 网关，生态成熟，插件丰富。

**为什么选 Kong**：
- 基于 OpenResty，和我们之前的 Nginx + Lua 技术栈一致
- 插件生态丰富，鉴权、限流、日志、监控都有现成插件
- 有管理 API 和 Dashboard，配置管理方便
- 支持数据库（PostgreSQL/Cassandra）和 DB-less 模式
- 社区活跃，文档完善

**Kong 架构**：
```text
客户端 → Kong（OpenResty + Lua 插件）→ 后端服务
              ↓
         PostgreSQL（配置存储）
              ↓
         Kong Admin API / Dashboard
```

**使用体验**：
- 插件确实丰富，常用的都有，不用自己写
- Admin API 方便，配置可以通过 API 动态更新，不用 reload
- Dashboard 可视化管理，运维方便
- 性能不错，单实例能扛 1万+ QPS

**遇到的问题**：
1. **PostgreSQL 依赖**：Kong 的配置存在 PostgreSQL 里，网关依赖数据库，数据库挂了网关就挂了。虽然有 DB-less 模式，但功能受限
2. **插件开发复杂**：自定义插件要用 Lua，而且要遵循 Kong 的插件开发规范，开发和调试成本高
3. **配置同步延迟**：多实例部署时，配置变更通过数据库轮询同步，有秒级延迟
4. **性能瓶颈**：高并发下（5万+ QPS），Kong 的 Lua 插件链有性能损耗，需要更多实例
5. **云原生支持一般**：Kong 虽然有 K8s Ingress Controller，但不是为云原生设计的，和 K8s 生态集成不够好
6. **企业版功能限制**：一些高级功能（如企业级插件、技术支持）需要付费

用了三年 Kong，整体满意，但随着流量增长和云原生转型，开始考虑下一代网关。

---

### 第三代：APISIX

Apache APISIX 是基于 etcd + Nginx 的云原生 API 网关，2025年已经非常成熟了。

**为什么换 APISIX**：
1. **性能更强**：基于 etcd 做配置存储，watch 机制实时同步，比 Kong 的数据库轮询快很多
2. **云原生设计**：专为云原生设计，K8s Ingress Controller 成熟，支持 Service Mesh
3. **插件生态丰富**：100+ 插件，比 Kong 还多，而且插件开发更简单（支持 Lua/Go/Python/Java 多语言）
4. **无数据库依赖**：配置存在 etcd，没有单点数据库依赖，etcd 本身就是高可用的
5. **动态配置**：所有配置（路由、上游、插件）都能动态更新，不需要 reload
6. **Apache 顶级项目**：社区活跃，国内有支流科技团队支持，中文文档好
7. **多语言插件**：插件可以用 Go/Python/Java 写，不用非得学 Lua，团队开发成本低

## 三、Kong vs APISIX 详细对比

| 维度 | Kong | APISIX |
|------|------|--------|
| 底层 | OpenResty (Nginx + Lua) | Nginx + etcd |
| 配置存储 | PostgreSQL/Cassandra/DB-less | etcd |
| 配置同步 | 数据库轮询（秒级延迟） | etcd watch（毫秒级） |
| 性能（QPS/实例） | ~1万 | ~2万（同配置下约2倍） |
| 延迟 P99 | ~5ms | ~2ms |
| 插件数量 | 80+ | 100+ |
| 插件开发语言 | Lua | Lua/Go/Python/Java（多语言） |
| 热更新 | 支持（Admin API） | 支持（etcd watch，更快） |
| K8s Ingress | 支持（较成熟） | 支持（更成熟，云原生设计） |
| Service Mesh | 支持（Kong Mesh） | 支持（与 Istio 集成） |
| 管理界面 | Kong Manager（企业版）/ Dashboard（社区） | APISIX Dashboard（开源） |
| 数据库依赖 | 有（PostgreSQL） | 无（etcd） |
| 社区 | 成熟，海外为主 | 活跃，国内团队主导 |
| 中文文档 | 一般 | 好 |
| 企业版 | 有（功能限制） | 有（支流科技，开源版功能全） |

### 性能压测数据

我们在相同环境下做了压测（4核8G，1000并发，HTTP 短连接）：

| 指标 | Kong | APISIX |
|------|------|--------|
| QPS | 12,500 | 24,800 |
| P50 延迟 | 1.2ms | 0.8ms |
| P99 延迟 | 8.5ms | 3.2ms |
| CPU 使用率 | 85% | 65% |
| 内存使用 | 1.2GB | 800MB |
| 错误率 | 0.1% | 0.01% |

APISIX 性能大约是 Kong 的 2 倍，延迟更低，资源占用更少。这是我们决定迁移的主要原因之一——同样的机器能扛两倍流量，省一半服务器成本。

## 四、迁移方案

从 Kong 迁移到 APISIX，我们用了"双跑 + 灰度"的方案，零停机迁移。

### 步骤1：配置迁移

写了个脚本把 Kong 的配置（路由、服务、插件）导出，转换成 APISIX 的配置格式：

```python
import requests

# 从 Kong Admin API 导出配置
kong_routes = requests.get("http://kong-admin:8001/routes").json()
kong_services = requests.get("http://kong-admin:8001/services").json()
kong_plugins = requests.get("http://kong-admin:8001/plugins").json()

# 转换成 APISIX 格式并导入
for route in kong_routes["data"]:
    apisix_route = {
        "uri": route["paths"][0],
        "methods": route.get("methods", ["GET", "POST"]),
        "upstream": {
            "type": "roundrobin",
            "nodes": {
                f"{service['host']}:{service['port']}": 1
                for service in kong_services["data"]
                if service["id"] == route["service"]["id"]
            }
        },
        "plugins": convert_plugins(route.get("plugins", []))
    }
    requests.put("http://apisix-admin:9180/apisix/admin/routes", 
                 json=apisix_route,
                 headers={"X-API-KEY": "admin-key"})
```

插件转换是重点，Kong 和 APISIX 的插件名和参数格式不一样，需要逐个映射：
- Kong 的 `key-auth` → APISIX 的 `key-auth`
- Kong 的 `rate-limiting` → APISIX 的 `limit-req`
- Kong 的 `jwt` → APISIX 的 `jwt-auth`
- Kong 的 `http-log` → APISIX 的 `http-logger`

自定义插件需要用 APISIX 的插件规范重写，我们用 Go 写了几个自定义插件，比 Lua 开发效率高很多。

### 步骤2：双跑验证

部署 APISIX 集群，和 Kong 并行运行，用流量复制验证：

```text
                    ┌──→ Kong（旧）→ 后端
客户端 → 负载均衡 ──┤
                    └──→ APISIX（新）→ 后端（影子流量，不返回给客户端）
```

用 GoReplay 或 Nginx mirror 把流量复制一份到 APISIX，对比两个网关的响应（状态码、响应体、延迟），确保 APISIX 的行为和 Kong 一致。

跑了一周影子流量，发现了几个问题：
1. APISIX 的路由匹配顺序和 Kong 不一样，有些路由匹配错了 → 调整路由优先级
2. 限流插件的参数格式不同，限流阈值不对 → 修正参数
3. 自定义 header 处理有差异 → 加插件统一处理

修复后，两个网关的响应一致性达到 99.9%。

### 步骤3：灰度切换

通过负载均衡按比例切流量：

```text
第1天：1% 流量到 APISIX，99% 到 Kong
第3天：10% 流量到 APISIX
第5天：30% 流量到 APISIX
第7天：50% 流量到 APISIX
第10天：100% 流量到 APISIX
```

每个阶段观察错误率、延迟、后端服务状态，没问题再加大比例。出问题一键切回 Kong，零风险。

### 步骤4：下线 Kong

100% 流量切到 APISIX 后，观察一周稳定，然后：
1. 停止 Kong 实例
2. 清理 Kong 的 PostgreSQL 数据库
3. 更新文档和运维手册

整个迁移过程 3 周，零停机，用户无感知。

## 五、APISIX 实践

### 插件开发（Go 语言）

APISIX 支持 Go 写插件（通过 Go Plugin Runner），不用学 Lua：

```go
// 自定义插件：招聘平台统一鉴权
package main

import (
    "github.com/apache/apisix-go-plugin-runner/go/internal"
    "github.com/apache/apisix-go-plugin-runner/go/plugin"
)

// 注册插件
func init() {
    plugin.RegisterPlugin(&RecruitAuth{})
}

type RecruitAuth struct {
    Name string
}

func (p *RecruitAuth) GetName() string {
    return "recruit-auth"
}

// ParseConf 解析插件配置
func (p *RecruitAuth) ParseConf(data []byte) (interface{}, error) {
    var conf struct {
        TokenHeader string `json:"token_header"`
        WhiteList   []string `json:"white_list"`
    }
    if err := json.Unmarshal(data, &conf); err != nil {
        return nil, err
    }
    return conf, nil
}

// RequestFilter 请求过滤（鉴权）
func (p *RecruitAuth) RequestFilter(conf interface{}, w http.ResponseWriter, r pkgHTTP.Request) {
    config := conf.(struct {
        TokenHeader string
        WhiteList   []string
    })

    // 白名单路径跳过鉴权
    for _, path := range config.WhiteList {
        if strings.HasPrefix(r.Path().String(), path) {
            return
        }
    }

    // 校验 Token
    token := r.Header().Get(config.TokenHeader)
    if token == "" || !validateToken(token) {
        w.WriteHeader(401)
        w.Write([]byte(`{"code":401,"message":"未授权"}`))
        return
    }

    // 把用户信息注入 header，传给后端
    userInfo := parseToken(token)
    r.Header().Set("X-User-ID", strconv.FormatInt(userInfo.ID, 10))
    r.Header().Set("X-User-Role", userInfo.Role)
}
```

在路由里启用插件：

```json
{
  "uri": "/api/resume/*",
  "plugins": {
    "recruit-auth": {
      "token_header": "Authorization",
      "white_list": ["/api/resume/public"]
    },
    "limit-req": {
      "rate": 100,
      "burst": 50,
      "key": "remote_addr"
    },
    "prometheus": {}
  },
  "upstream": {
    "type": "roundrobin",
    "nodes": {
      "resume-service:8080": 1
    }
  }
}
```

### 灰度发布

APISIX 的 traffic-split 插件支持灰度：

```json
{
  "uri": "/api/resume/*",
  "plugins": {
    "traffic-split": {
      "rules": [
        {
          "match": [
            {
              "vars": [["http_x_user_type", "==", "internal"]]
            }
          ],
          "weighted_upstreams": [
            {
              "upstream": {
                "name": "resume-service-v2",
                "nodes": {
                  "resume-service-v2:8080": 1
                }
              },
              "weight": 1
            }
          ]
        }
      ]
    }
  },
  "upstream": {
    "type": "roundrobin",
    "nodes": {
      "resume-service-v1:8080": 1
    }
  }
}
```

内部用户（x-user-type: internal）走 v2，其他走 v1。也可以按比例灰度，配置 weight 就行。

### 监控集成

APISIX 内置 Prometheus 插件，暴露指标：

```json
{
  "plugins": {
    "prometheus": {}
  }
}
```

Prometheus 采集后，Grafana 有现成的 APISIX dashboard，能看到 QPS、延迟、错误率、上游状态、带宽等。

## 六、踩坑经验

1. **etcd 性能瓶颈**：APISIX 配置存在 etcd，路由数量多了之后（几千条），etcd 的 watch 事件量大，APISIX 实例启动时同步配置慢。etcd 要做好性能优化，SSD 磁盘，合理配置 compaction
2. **插件顺序很重要**：APISIX 插件按固定顺序执行（鉴权 → 限流 → 日志），自定义插件要注意执行顺序，否则可能出现"先限流再鉴权"之类的逻辑错误
3. **路由匹配规则**：APISIX 的路由匹配和 Kong/Nginx 有差异，特别是正则匹配和优先级。迁移时要逐条验证路由，最好用自动化测试对比
4. **长连接超时**：APISIX 默认的 upstream 超时时间较短，长连接（WebSocket、gRPC stream）容易断开。要在 upstream 配置里调大 keepalive_timeout 和 idle_timeout
5. **大请求体**：APISIX 默认 client_max_body_size 是 100MB，文件上传接口可能超限。在路由配置里调大，或者用专门的文件上传服务
6. **插件热更新**：APISIX 的路由和插件配置是热更新的，但插件代码（特别是 Go 插件）更新需要重启 Go Plugin Runner。Go 插件开发时要注意，改了代码要重启 runner
7. **多语言插件通信开销**：Go/Python 插件通过 Unix Socket 和 APISIX 通信，有一定性能开销。高性能要求的插件还是用 Lua 写，业务逻辑类插件用 Go 写没问题
8. **Dashboard 权限**：APISIX Dashboard 默认 admin 权限很大，生产环境要做权限控制，只给运维人员访问，不要暴露在公网

## 七、总结

API 网关演进核心：

1. **自研 → 开源产品是必然**：服务数量多了之后，自研网关的维护成本太高，成熟的开源产品（Kong/APISIX）生态好、功能全、更稳定
2. **Kong 到 APISIX 是性能和云原生的升级**：APISIX 性能约 2 倍，延迟更低，云原生设计更好，etcd 配置存储无数据库依赖
3. **迁移要双跑+灰度**：不要一次性切换，用流量复制验证一致性，按比例灰度切换，出问题一键回滚，零停机迁移
4. **插件开发多语言是优势**：APISIX 支持 Go/Python/Java 写插件，团队不用学 Lua，开发效率高，这是相比 Kong 的一大优势
5. **性能压测是选型依据**：不要只看文档和口碑，在自己的环境、自己的流量模型下压测，用数据说话
6. **etcd 是 APISIX 的核心**：配置存在 etcd，etcd 的性能和稳定性直接影响网关，要做好 etcd 的高可用和性能优化
7. **插件顺序和路由匹配是迁移坑点**：不同网关的插件执行顺序和路由匹配规则有差异，迁移时要逐条验证，最好自动化对比
8. **网关是基础设施，稳定优先**：网关是所有流量的入口，稳定性比功能更重要。新版本升级、配置变更都要灰度，不要在生产环境冒险

API 网关的演进反映了技术架构的演进——从单体 Nginx 到微服务网关，从数据库存储到 etcd 云原生，从 Lua 插件到多语言插件。技术在变，但核心需求没变：高性能、高可用、易扩展、易维护。选型时不要追新，要根据自己的业务规模、团队能力、性能需求综合判断。Kong 和 APISIX 都是优秀的网关，小团队用 Kong 也完全没问题，大流量、云原生场景 APISIX 更合适。
