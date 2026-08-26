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
