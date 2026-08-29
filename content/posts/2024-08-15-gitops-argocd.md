---
title: "GitOps with ArgoCD：声明式持续交付多环境实践"
date: 2024-08-15T10:00:00+08:00
draft: false
tags: ["GitOps", "ArgoCD", "K8s", "CI/CD", "持续交付", "DevOps"]
categories: ["云原生"]
summary: "基于 ArgoCD 的 GitOps 持续交付实践，涵盖多环境管理、应用声明式配置、自动同步、回滚、权限控制，解决传统 CI/CD 流水线配置散乱、环境不一致的问题。"
---

传统 CI/CD 用 Jenkins 流水线做部署，每个环境的配置散落在 Jenkinsfile、脚本、环境变量里，环境之间经常不一致，出问题排查困难。2024年中我们引入了 ArgoCD，改成 GitOps 模式——所有环境配置都存在 Git 仓库里，ArgoCD 自动同步到 K8s 集群。今天把实践经验分享出来。

## 一、GitOps 核心思想

GitOps 的四个原则：

1. **声明式**：系统的所有配置（Deployment、Service、ConfigMap 等）都是声明式的，存在 Git 里
2. **版本控制**：Git 是唯一的事实来源，所有变更通过 Git commit 记录，可追溯、可回滚
3. **自动同步**：ArgoCD 持续监控 Git 仓库和集群状态，发现不一致自动同步
4. **闭环验证**：同步后自动验证应用健康状态，不健康自动告警

核心好处：**Git 是唯一入口**，不用给每个人 K8s 集群权限，所有变更走 Git PR，审核后合并，ArgoCD 自动部署。

## 二、架构

```text
开发者 → Git 提交 → ArgoCD 检测变更 → 同步到 K8s 集群
                ↑                          ↓
           配置仓库（Git）            应用健康检查
```

- **配置仓库**：所有环境的 K8s 配置都存在这里，分目录管理
- **ArgoCD**：监控 Git 仓库，发现变更后自动同步到集群，监控应用健康
- **K8s 集群**：实际运行应用的地方

## 三、仓库结构

用一个 Git 仓库管理所有环境的配置：

```text
deploy-repo/
├── apps/                          # 应用配置
│   ├── resume-service/
│   │   ├── base/                  # 基础配置（所有环境共用）
│   │   │   ├── deployment.yaml
│   │   │   ├── service.yaml
│   │   │   └── kustomization.yaml
│   │   └── overlays/              # 环境覆盖
│   │       ├── dev/
│   │       │   ├── kustomization.yaml
│   │       │   └── replicas-patch.yaml  # dev 环境1个副本
│   │       ├── staging/
│   │       │   ├── kustomization.yaml
│   │       │   └── replicas-patch.yaml  # staging 2个副本
│   │       └── prod/
│   │           ├── kustomization.yaml
│   │           └── replicas-patch.yaml  # prod 5个副本
│   └── job-service/
│       └── ...
├── argocd/                        # ArgoCD Application 定义
│   ├── dev/
│   │   └── resume-service.yaml
│   ├── staging/
│   └── prod/
└── README.md
```

用 Kustomize 管理多环境，base 是通用配置，overlays 是每个环境的差异（副本数、镜像版本、环境变量等）。

### base 配置

```yaml
# apps/resume-service/base/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: resume-service
spec:
  selector:
    matchLabels:
      app: resume-service
  template:
    metadata:
      labels:
        app: resume-service
    spec:
      containers:
        - name: resume-service
          image: registry.example.com/resume-service:latest
          ports:
            - containerPort: 8080
          env:
            - name: GIN_MODE
              value: release
```

```yaml
# apps/resume-service/base/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - deployment.yaml
  - service.yaml
```

### 环境覆盖

```yaml
# apps/resume-service/overlays/prod/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: prod
resources:
  - ../../base
patches:
  - path: replicas-patch.yaml
images:
  - name: registry.example.com/resume-service
    newTag: v1.5.2  # prod 环境固定版本
```

```yaml
# apps/resume-service/overlays/prod/replicas-patch.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: resume-service
spec:
  replicas: 5
```

每个环境的镜像版本、副本数、环境变量都在 overlays 里配置，base 保持通用。

## 四、ArgoCD Application 定义

```yaml
# argocd/prod/resume-service.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: resume-service-prod
  namespace: argocd
spec:
  project: prod
  source:
    repoURL: git@github.com:example/deploy-repo.git
    targetRevision: main
    path: apps/resume-service/overlays/prod
  destination:
    server: https://kubernetes.default.svc
    namespace: prod
  syncPolicy:
    automated:
      prune: true      # 自动删除 Git 里不存在的资源
      selfHeal: true   # 集群状态和 Git 不一致时自动修复
    syncOptions:
      - CreateNamespace=true  # 自动创建命名空间
  revisionHistoryLimit: 10  # 保留最近10个版本，用于回滚
```

ArgoCD 监控 `deploy-repo` 仓库的 `apps/resume-service/overlays/prod` 目录，发现变更自动同步到 prod 命名空间。

## 五、部署流程

### 正常发布

1. 开发者提交代码到应用仓库，CI 构建镜像并推送到镜像仓库
2. CI 自动更新 deploy-repo 里对应环境的镜像版本（改 `newTag`）
3. ArgoCD 检测到 deploy-repo 变更，自动同步到 K8s 集群
4. ArgoCD 监控应用健康状态，不健康自动告警

```bash
# CI 里更新镜像版本的脚本
kustomize edit set image registry.example.com/resume-service:${IMAGE_TAG}
git add .
git commit -m "chore: update resume-service to ${IMAGE_TAG}"
git push
```

### 回滚

出问题时回滚超简单，Git revert 就行：

```bash
git revert <commit-hash>  # 回退到上一个版本
git push
# ArgoCD 自动检测到变更，同步回滚
```

或者在 ArgoCD UI 里点回滚按钮，选历史版本一键回滚。

## 六、多环境管理

用 ArgoCD Projects 隔离环境权限：

```yaml
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: prod
  namespace: argocd
spec:
  description: Production environment
  sourceRepos:
    - git@github.com:example/deploy-repo.git
  destinations:
    - namespace: prod
      server: https://kubernetes.default.svc
  clusterResourceWhitelist:
    - group: ''
      kind: Namespace
  roles:
    - name: developer
      description: Developer can view but not sync
      policies:
        - p, proj:prod:developer, applications, get, prod/*, allow
        - p, proj:prod:developer, applications, sync, prod/*, deny
      groups:
        - developers
    - name: sre
      description: SRE can sync and manage
      policies:
        - p, proj:sre, applications, *, prod/*, allow
      groups:
        - sre
```

开发者只能看 prod 环境，不能手动同步；SRE 才有完整权限。所有变更必须走 Git PR。

## 七、ArgoCD Image Updater

自动更新镜像版本，不用 CI 脚本改 Git：

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: resume-service-dev
  annotations:
    argocd-image-updater.argoproj.io/image-list: resume=registry.example.com/resume-service
    argocd-image-updater.argoproj.io/resume.update-strategy: semver
    argocd-image-updater.argoproj.io/resume.allow-tags: regexp:^v\d+\.\d+\.\d+$
```

ArgoCD Image Updater 自动监控镜像仓库，发现新版本自动更新 Application 的镜像 tag，触发同步。dev 环境可以用 latest 或 semver 自动更新，prod 环境固定版本手动更新。

## 八、踩坑经验

1. **配置漂移**：有人直接用 kubectl 改了集群配置，和 Git 不一致，ArgoCD 自动同步又改回去了。开了 selfHeal 后这种情况会被自动修复，但要教育团队不要直接改集群
2. **Secret 管理**：ConfigMap 可以存 Git，但 Secret 不能明文存。用 Sealed Secrets 或 External Secrets，加密后存 Git，ArgoCD 同步时自动解密
3. **大仓库性能**：所有应用的配置都在一个仓库，ArgoCD 检测变更时要 clone 整个仓库，慢。按团队或业务拆分成多个仓库，或者用 monorepo + ArgoCD 的 path 过滤
4. **CRD 依赖**：有些应用依赖 CRD（如 Istio VirtualService），ArgoCD 同步时 CRD 还没创建好，应用同步失败。用 sync waves 控制同步顺序，先同步 CRD 再同步应用
5. **回滚不彻底**：Git revert 只回滚了配置，但数据库 schema 变更没回滚。数据库变更要单独管理，向前兼容设计，回滚时数据库不用回退
6. **多集群管理**：ArgoCD 可以管理多个 K8s 集群，但集群多了之后 Application 数量爆炸。用 ApplicationSet 批量生成 Application，按集群标签自动生成

## 九、效果

| 指标 | GitOps 前 | GitOps 后 |
|------|----------|----------|
| 部署频率 | 每周2次 | 每天多次 |
| 部署时间 | 30分钟（人工操作） | 2分钟（自动同步） |
| 回滚时间 | 15分钟（重新部署） | 30秒（Git revert） |
| 环境一致性 | 经常不一致 | Git 是唯一来源，完全一致 |
| 变更审计 | 靠 Jenkins 日志 | Git commit 全记录，可追溯 |
| 权限管理 | 每人都有 K8s 权限 | 只有 SRE 有，开发者走 PR |

## 十、总结

GitOps with ArgoCD 核心：

1. **Git 是唯一事实来源**：所有配置存 Git，变更走 PR，审核后合并，自动部署
2. **声明式配置**：Kustomize 管理多环境，base 通用 + overlays 差异，配置清晰
3. **自动同步**：ArgoCD 监控 Git，变更自动同步，selfHeal 修复配置漂移
4. **一键回滚**：Git revert 或 ArgoCD UI 回滚，秒级生效
5. **权限隔离**：ArgoCD Projects + RBAC，开发者只读，SRE 可操作，安全可控
6. **可观测**：ArgoCD UI 看应用健康状态、同步历史、差异对比，出问题一目了然

GitOps 最大的价值不是"自动部署"，而是"把基础设施配置纳入版本控制，让变更可追溯、可回滚、可审计"。传统 CI/CD 是"推送式"——流水线把配置推到集群，出问题不知道当前集群跑的是什么版本；GitOps 是"拉取式"——ArgoCD 从 Git 拉配置，集群状态永远和 Git 一致，Git 里是什么集群就是什么。对于多环境、多服务、多团队的复杂系统，GitOps 能大幅降低运维成本和出错概率。
