# 图床方案（Fluxio 博客图片管理规范）

> 适用：手写图文并茂文章时，图片的存放、命名与引用方式。
> 方案选定：**静态资源随站发布，走 ESA 全站 CDN**（成本 0、自动国内节点加速、无需额外图床服务）。

## 为什么选"随站发布"而不是外部图床

| 方案 | 成本 | 加速 | 维护 | 结论 |
|---|---|---|---|---|
| **static/images 随站发布（ESA CDN）** | 0 | 阿里云 ESA 全球节点，国内优 | 图片随 git 版本化，push 即上线 | ✅ 采用 |
| GitHub 仓库 + jsDelivr | 0 | jsDelivr 海外节点，国内一般 | 需单独图床仓库 | 备选 |
| 阿里云 OSS + CDN | 按量计费 | 国内好 | 需配 bucket/回源 | 量大再说 |
| Cloudflare R2 | 0~低 | 海外节点 | 需配 worker 绑定域名 | 备选 |

> 说明：主站已通过 Gitee → GitHub → ESA 自动构建上线，图片放入 `static/images/` 即可随站自动部署，天然 CDN 加速，无需单独图床。

## 图片目录规范

```
static/images/posts/
├── <文章slug>/          # 长文多图按文章 slug 分子目录（推荐）
│   ├── 01-架构图.webp
│   ├── 02-时序图.webp
│   └── cover.webp
└── <短名>.webp          # 单图/散图直接放平级
```

## 命名规范

- **语义化英文短横线命名**，如 `docker-arch.webp`、`es-cluster.webp`、`mycat-sharding.webp`
- 禁止无意义 hash 命名（如 `25bc1744c1d4.gif`）——历史遗留，新图不再用
- 中文长文按文章建子目录，文件名带序号保证顺序

## 格式与体积

- **优先 WebP**（体积小、质量好）；动图用 GIF；截图/照片也可用 jpg/png
- 单图尽量 ≤ 300KB；超大图先用工具压缩（可用 `scripts/_opt_images.py`）
- 封面图统一放 `static/images/` 平级并命名 `cover.webp` 或 `og-cover.jpg`

## Markdown 引用方式

```markdown
![架构图说明](/images/posts/docker-arch.webp)

<!-- 长文子目录示例 -->
![时序说明](/images/posts/2025-mcp-gateway/02-时序图.webp)
```

> 必须用绝对路径 `/images/...`（以站点根开始），不要用相对路径，避免列表/详情页路径错位。

## 手写图文文章的流程

1. 先建子目录 `static/images/posts/<文章slug>/`
2. 图片统一转 WebP、压缩到 ≤300KB
3. 正文用 `![描述](/images/posts/<slug>/<序号-名称>.webp)` 引用
4. 封面放 front matter：`cover: { image: images/posts/<slug>/cover.webp }`
5. `hugo serve` 本地预览 → `git push` 自动上线
