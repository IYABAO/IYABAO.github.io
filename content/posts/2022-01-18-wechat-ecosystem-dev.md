---
title: "微信生态开发：支付、登录与开放平台的坑"
date: 2022-01-18T09:00:00+08:00
lastmod: 2022-01-18T09:00:00+08:00
draft: false
author: IYABAO
tags:
  - 微信
  - 支付
  - 开放平台
categories:
  - 技术
summary: "小程序、公众号、支付、开放平台——微信生态的每一块都有自己的一套规则。自动授权、支付回调、退款、开放平台绑定：六年微信开发的踩坑全记录。"
---

# 微信生态开发：支付、登录与开放平台的坑

微信生态不是"一个 API"，是**一套规则**：小程序、公众号、开放平台、支付，每个都有自己的凭证、接口和坑。这篇文章是六年微信开发（小程序/服务号/支付/开放平台）的踩坑总结。

## 一、三种身份凭证

| 凭证 | 用途 | 有效期 |
|---|---|---|
| **AppID + AppSecret** | 公众号/小程序的身份 | 永久 |
| **access_token** | 调用接口的令牌 | 2 小时，需缓存刷新 |
| **openid / unionid** | 用户身份 | 永久 |

**核心概念**：

```
openid：同一公众号/小程序下，同一用户的唯一 ID（不同应用下不同）
unionid：同一开放平台账号下，所有应用的统一用户 ID（打通小程序+公众号+App）

场景：用户在小程序下单，公众号要给他发通知
  → 必须用 unionid 关联（openid 对不上）
  → 前提：小程序和公众号都绑定到同一个开放平台账号
```

## 二、微信登录（自动授权）

```
流程：
  前端 wx.login() → 拿 code
  → 后端 code2Session → 拿 openid + session_key（小程序）
  → 生成业务 token → 返回前端
```

```go
// 后端（小程序登录）
func WxLogin(ctx, code string) (*LoginResult, error) {
    resp, _ := http.Get(fmt.Sprintf(
        "https://api.weixin.qq.com/sns/jscode2session"+
        "?appid=%s&secret=%s&js_code=%s&grant_type=authorization_code",
        appid, secret, code))
    // resp: {openid, session_key, unionid}
    user := findOrCreateByOpenid(resp.Openid)
    return issueToken(user), nil
}
```

**坑**：

```
✅ code 只能用一次（前端误重发 → 失败）
✅ code 有效期 5 分钟（过期失效）
✅ session_key 不要下发前端（敏感）
✅ 手机号解密需要 session_key（用后即换）
```

## 三、微信支付

### 核心流程

```
用户下单 → 后端生成预支付单（统一下单）
→ 返回支付参数 → 前端拉起支付
→ 用户支付 → 微信回调 notify_url（异步！）
→ 后端验签 + 查单确认 → 更新订单
```

### 关键：支付回调（最容易错的）

```go
func PayNotify(w http.ResponseWriter, r *http.Request) {
    // 1. 读回调（XML/JSON）
    body := readBody(r)
    // 2. 验签（用 APIv3 密钥/证书）
    if !verifySignature(r, body) {
        w.WriteHeader(401); return   // 验签失败：不返回成功
    }
    // 3. 查单确认（别只信回调！回调可能重复/伪造）
    order := wx.QueryOrder(body.OutTradeNo)
    if order.Status != "SUCCESS" {
        w.WriteHeader(400); return
    }
    // 4. 幂等更新（回调可能来多次！）
    if !markOrderPaid(order.OutTradeNo) {   // DB 幂等
        w.WriteHeader(200); return          // 已处理过：返回成功（不重发）
    }
    // 5. 必须返回成功（否则微信会重试 24h！）
    w.WriteHeader(200)
}
```

**回调的铁律**：

```
✅ 验签不过 → 不返回成功（微信会重试）
✅ 只信"查单结果"，不信回调内容（回调可伪造/重复）
✅ 幂等处理（重复回调不重复发货）
✅ 必须返回成功（返回失败 = 微信重试 24 小时 = 重复回调风暴）
```

### 退款

```
退款比支付更容易踩坑：
  1. 退款需要证书（APIv3 证书，不是密钥）
  2. 退款金额不能超过可退金额（部分退 vs 全额退）
  3. 退款结果也是异步通知（退款单状态轮询/回调）
  4. 退款幂等：退款单号唯一（重试用同一退款单号）
```

## 四、开放平台

```
开放平台的坑：
  1. 小程序/公众号绑定开放平台才能拿 unionid
  2. 绑定后不可轻易解绑（影响数据打通）
  3. 第三方平台（代开发）权限要"授权托管"
  4. 多主体：不同主体的小程序不能共用一个开放平台
```

## 五、防重与安全

```
✅ access_token 全局缓存 + 刷新锁（多实例并发刷会互踢！）
✅ 支付回调幂等（订单状态机：待支付→已支付→已发货）
✅ 敏感接口校验（openid 与 token 用户一致）
✅ 金额单位：分（整型，别用浮点！）
✅ 回调来源校验（验 IP/验签名，防伪造回调）
```

## 六、踩坑记录

1. **access_token 并发刷新互踢**：多个实例同时刷新 → 旧的失效，新的也失效 → 加分布式锁 + 本地缓存
2. **金额用浮点**：0.1 + 0.2 = 0.30000000000000004 → 订单金额错 → **一律用"分"（整数）**
3. **回调重复触发**：返回非 200 → 微信重试 24h → 幂等处理 + 必须返回成功
4. **unionid 拿不到**：小程序没绑开放平台 → 调接口没 unionid → 先绑再开发

## 总结

微信生态的核心认知：

1. **三种凭证 + 两种用户 ID**：openid 应用内唯一，unionid 跨应用打通
2. **支付回调四铁律**：验签、查单、幂等、必返成功
3. **金额用分**：整数运算，浮点是事故源
4. **access_token 全局管理**：缓存 + 刷新锁，防互踢

**微信生态的复杂度不在"接口多"，在"状态机多"**：登录态、支付态、退款态，每个状态转换都有规则和坑。把状态机画清楚，微信开发就成功了一半。
