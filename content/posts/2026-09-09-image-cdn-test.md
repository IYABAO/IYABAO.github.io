---
title: "博客图床方案：GitHub + jsDelivr CDN 配置实战"
date: 2026-09-09T15:40:00+08:00
draft: false
tags: ["Hugo", "图床", "CDN", "jsDelivr", "博客优化"]
categories: ["工程效能"]
summary: "从零配置 GitHub + jsDelivr CDN 免费图床方案，实现博客图片的快速访问与管理。"
---

## 为什么需要图床方案

写技术博客时，图文并茂能大幅提升阅读体验。但图片存储和访问是个问题：

1. **图片和文章放一起**：仓库越来越大，clone 慢
2. **直接用 GitHub raw 链接**：国内访问速度慢，经常超时
3. **付费图床**：成本高，个人博客没必要
4. **第三方免费图床**：不稳定，随时可能挂掉

**GitHub + jsDelivr CDN** 是最佳免费方案：
- GitHub 做存储，免费无限容量（单文件≤25MB）
- jsDelivr 做 CDN 加速，国内有节点，访问速度快
- 完全免费，无需付费
- 与博客源码同仓库，管理方便

## 方案架构

{{< img src="2026-09-09-001-cdn-test.svg" alt="GitHub + jsDelivr CDN 架构图" caption="图1：GitHub + jsDelivr CDN 图床方案架构" >}}

**工作流程**：
1. 图片存放在博客仓库的 `static/images/` 目录
2. 推送代码到 GitHub
3. jsDelivr CDN 自动缓存 GitHub 仓库文件
4. 文章中通过 jsDelivr CDN 链接引用图片
5. 用户访问时从最近的 CDN 节点加载图片

## 配置步骤

### 1. 目录结构

```text
plbear-blog/
├── static/
│   └── images/           # 图片存放目录
│       ├── 2026-09-09-001-cdn-test.svg
│       └── ...
├── layouts/
│   └── shortcodes/
│       └── img.html      # 图片短代码
├── scripts/
│   └── upload-image.py   # 图片上传脚本
└── hugo.toml             # CDN 配置
```

### 2. Hugo 配置

在 `hugo.toml` 中添加 CDN 配置：

```toml
[params.imageCDN]
  enable = true
  baseURL = "https://cdn.jsdelivr.net/gh/IYABAO/IYABAO.github.io@master/static/images/"
  useInDev = false
  lazyLoad = true
```

### 3. 图片短代码

创建 `layouts/shortcodes/img.html`，自动使用 CDN 链接：

```html
{{- $src := .Get "src" -}}
{{- $alt := .Get "alt" | default "" -}}
{{- $cdnBase := .Site.Params.imageCDN.baseURL -}}

<img src="{{ $cdnBase }}{{ $src }}" alt="{{ $alt }}" loading="lazy" />
```

### 4. 使用方式

在文章中用短代码引用图片：

```markdown
{{< img src="xxx.png" alt="图片描述" caption="图片说明" >}}
```

### 5. 图片上传脚本

用 Python 脚本一键复制图片并重命名：

```bash
python scripts/upload-image.py C:/Users/xxx/Pictures/screenshot.png 架构图
```

输出：
```text
✅ 图片已复制到: static/images/2026-09-09-001-架构图.png
🌐 CDN 链接: https://cdn.jsdelivr.net/gh/.../2026-09-09-001-架构图.png
📝 Hugo 短代码: {{< img src="2026-09-09-001-架构图.png" alt="架构图" >}}
```

## jsDelivr CDN 优势

| 特性 | 说明 |
|------|------|
| **免费** | 完全免费，无流量限制 |
| **国内加速** | 国内有 CDN 节点，访问速度快 |
| **自动缓存** | 推送 GitHub 后自动缓存 |
| **版本管理** | 支持指定分支/Tag/Commit |
| **刷新缓存** | 支持主动刷新 CDN 缓存 |
| **HTTPS** | 默认支持 HTTPS |

## 注意事项

1. **单文件大小**：GitHub 单文件建议 ≤25MB，超过会有警告
2. **CDN 缓存**：推送后可能需要几分钟才能生效，可主动刷新缓存
3. **图片命名**：建议用 `日期-序号-名称` 格式，避免重名
4. **本地开发**：`useInDev = false` 时本地用相对路径，不依赖 CDN
5. **仓库公开**：jsDelivr 只能访问公开仓库，私有仓库不行

## 刷新 CDN 缓存

如果图片更新了但 CDN 还是旧的，可以主动刷新：

```text
https://purge.jsdelivr.net/gh/IYABAO/IYABAO.github.io@master/static/images/文件名.png
```

## 总结

GitHub + jsDelivr CDN 是个人博客图床的最佳免费方案：
- **零成本**：完全免费
- **速度快**：国内 CDN 加速
- **管理方便**：与博客同仓库，Git 管理
- **可扩展**：后续可无缝迁移到其他图床

配置完成后，写文章时只需要用 `{{< img src="xxx.png" >}}` 短代码，图片就会自动通过 CDN 加速加载。
