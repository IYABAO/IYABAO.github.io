# Plbear Blog

基于 Hugo 的静态博客，部署于阿里云 ESA（边缘安全加速）。

## 技术栈

- **静态站点生成器**：Hugo (extended)
- **包管理**：npm（hugo-bin）
- **代码托管**：Gitee（主仓库）→ GitHub（镜像同步）
- **部署平台**：阿里云 ESA 函数和 Pages
- **域名**：www.plbear.com

## 本地开发

```bash
# 安装依赖
npm install

# 启动本地开发服务器（带草稿）
npm run server

# 新建文章
npm run new posts/my-first-post.md

# 构建生产版本
npm run build
```

## 目录结构

```
plbear-blog/
├── archetypes/     # 文章模板
├── content/        # 内容
│   └── posts/      # 博客文章
├── layouts/        # 自定义布局
├── static/         # 静态资源（图片、CSS、JS等）
├── themes/         # 主题
├── hugo.toml       # Hugo 配置
├── package.json    # npm 配置（ESA构建用）
└── .gitignore
```

## 图床方案（GitHub + jsDelivr CDN）

博客图片使用 **GitHub + jsDelivr CDN** 免费方案，国内访问速度快，零成本。

### 配置

在 `hugo.toml` 中已配置：

```toml
[params.imageCDN]
  enable = true
  baseURL = "https://cdn.jsdelivr.net/gh/IYABAO/IYABAO.github.io@master/static/images/"
  useInDev = false   # 本地开发时使用相对路径
  lazyLoad = true    # 图片懒加载
```

### 上传图片

使用上传脚本一键复制并重命名：

```bash
python scripts/upload-image.py <图片路径> [自定义名称]

# 示例
python scripts/upload-image.py C:/Users/xxx/Pictures/screenshot.png 架构图
```

输出示例：
```
✅ 图片已复制到: static/images/2026-09-09-001-架构图.png
🌐 CDN 链接: https://cdn.jsdelivr.net/gh/IYABAO/IYABAO.github.io@master/static/images/2026-09-09-001-架构图.png
📝 Hugo 短代码: {{< img src="2026-09-09-001-架构图.png" alt="架构图" >}}
```

### 文章中引用图片

使用 `img` 短代码（自动使用 CDN 链接）：

```markdown
{{< img src="2026-09-09-001-架构图.png" alt="系统架构图" caption="图1：系统整体架构" >}}
```

参数说明：
- `src`：图片文件名（必填，放在 `static/images/` 目录）
- `alt`：图片描述（可选，SEO 友好）
- `caption`：图片说明文字（可选，显示在图片下方）
- `width`：最大宽度（可选，单位 px）

### 刷新 CDN 缓存

图片更新后 CDN 可能还是旧的，主动刷新：

```
https://purge.jsdelivr.net/gh/IYABAO/IYABAO.github.io@master/static/images/文件名.png
```

### 注意事项

- 图片放在 `static/images/` 目录，命名格式：`日期-序号-名称.扩展名`
- GitHub 单文件建议 ≤25MB
- 仓库必须公开（jsDelivr 只能访问公开仓库）
- 推送代码到 GitHub 后 CDN 自动生效（可能延迟几分钟）

## 主题选择

推荐技术博客主题：
- **PaperMod**：简洁、轻量、功能全，最受欢迎
- **Stack**：现代卡片式设计，侧边栏
- **hugo-theme-stack**：同上，社区活跃
- **DoIt**：功能丰富，支持搜索、评论

安装主题方式（以 PaperMod 为例）：
```bash
git submodule add https://github.com/adityatelange/hugo-PaperMod themes/PaperMod
# 然后在 hugo.toml 中设置 theme = 'PaperMod'
```

## 从 Gridea 迁移

1. 将 Gridea 的文章 Markdown 文件复制到 `content/posts/`
2. 调整 front matter 格式（Gridea → Hugo）：
   - `date` 格式保持 `YYYY-MM-DD` 或 `YYYY-MM-DDTHH:MM:SS+08:00`
   - `tags` 从逗号分隔字符串改为数组：`['tag1', 'tag2']`
3. 将静态资源（图片等）复制到 `static/` 目录
4. 本地运行 `npm run server` 预览效果

## 部署

推送到 Gitee 后自动镜像到 GitHub，ESA 检测到 GitHub 仓库变更后自动构建部署。

ESA 构建配置：
- 安装命令：`npm install`
- 构建命令：`npm run build`
- 静态资源目录：`public`
- Node.js 版本：22.x
