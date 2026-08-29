---
title: "阿里云盘 挂载本地挂载"
date: 2022-06-24
draft: false
summary: "使用 Alist 将阿里云盘挂载到本地磁盘的完整教程：先通过开源网盘目录程序 Alist 管理网盘，再映射成本地网络磁盘，两步实现云盘本地化，在本地直接读写云盘文件。"
slug: "a-li-yun-pan-gua-zai-ben-di-gua-zai"
---

**Alist**

一般电脑上挂载云盘到本地都是两步走，先利用网盘目录程序搞定网盘，再映射成本地网络磁盘，所以想把网盘挂载到本地，我们需要两个工具。

当然，网盘目录程序有很多，不过你可以试试今天这个 Alist，开源在 GitHub 上，已经荣获了 6.2K+ Star。

![给你免费加个「8百万TB」的硬盘，你猜能存多少东西？](https://p6.toutiaoimg.com/origin/tos-cn-i-qvj2lq49k0/f50fce521cf24d97b90965af12898ee4?from=pc)

而且不光是阿里云盘，什么天翼云盘、谷歌云盘、123 云盘、蓝奏云、夸克网盘等等，Alist 可以一口气帮你聚合十几种网盘。

![给你免费加个「8百万TB」的硬盘，你猜能存多少东西？](https://p6.toutiaoimg.com/origin/tos-cn-i-qvj2lq49k0/3569de323d9c4a03827326366b880011?from=pc)

Alist 用起来很简单，双击解压后的可执行文件，你会看到这样一个运行窗口，里面记录了自动生成的密码，和本地访问的端口：

![给你免费加个「8百万TB」的硬盘，你猜能存多少东西？](https://p6.toutiaoimg.com/origin/tos-cn-i-qvj2lq49k0/8f7c504e1be1465eac1a7e814b184305?from=pc)

如果双击无反应，大家可以试试右键「以管理员身份运行」：

![给你免费加个「8百万TB」的硬盘，你猜能存多少东西？](https://p6.toutiaoimg.com/origin/tos-cn-i-qvj2lq49k0/9cc5db4ebb794de6aefc5540888c52cc?from=pc)

只要运行窗口正常弹出，Alist 在你电脑上就搭建好了，去浏览器上访问地址「127.0.0.1:5244」，输入刚刚生成的密码：

![给你免费加个「8百万TB」的硬盘，你猜能存多少东西？](https://p6.toutiaoimg.com/origin/tos-cn-i-qvj2lq49k0/d9b9b5fb8a504114bef3cef6dadc6892?from=pc)

你就进入 Alist 的管理后台了。

注意，我们最小化运行窗口就行，不要关闭，否则 Alist 会停止服务：

![给你免费加个「8百万TB」的硬盘，你猜能存多少东西？](https://p6.toutiaoimg.com/origin/tos-cn-i-qvj2lq49k0/3882ac7419df4b319d539c582dc06b9d?from=pc)

还有就是第一次配置 Alist 后，会生成一个配置文件，如果使用过程中有什么问题，把它删了，重新启动下面的可执行文件就行。

![给你免费加个「8百万TB」的硬盘，你猜能存多少东西？](https://p6.toutiaoimg.com/origin/tos-cn-i-qvj2lq49k0/21c9acfb405d48e2a13eb0a372798906?from=pc)

**增添网盘**

不过此时的 Alist 空空如也，不过别急，在左侧菜单「账号」处添加自己的网盘即可：

![给你免费加个「8百万TB」的硬盘，你猜能存多少东西？](https://p6.toutiaoimg.com/origin/tos-cn-i-qvj2lq49k0/f057e7524e98413e8a0165974e633d42?from=pc)

以阿里云盘为例，你会看到这样一个窗口，必填项有「虚拟路径」和「刷新令牌」，前者随意，后者则包含了我们登录信息的 token 值：

![给你免费加个「8百万TB」的硬盘，你猜能存多少东西？](https://p6.toutiaoimg.com/origin/tos-cn-i-qvj2lq49k0/7fe95e34e9e5437ba8e21302875e648b?from=pc)

别的网盘你可以在浏览器上获得 token，但阿里云盘只能用移动端的 token，不过贴心的是，作者提供了个提取移动端 token 的在线工具。

点击[「Get Token」](https://alist-doc.nn.ci/docs/driver/aliyundrive/
)，手机阿里云盘扫码即可获取：

![给你免费加个「8百万TB」的硬盘，你猜能存多少东西？](https://p6.toutiaoimg.com/origin/tos-cn-i-qvj2lq49k0/63fbc96845d24bfc9fcb1bf0f89c53f9?from=pc)

粘贴到 Alist 的管理后台，重新访问「127.0.0.1:5244」，你的 Alist 就该是这个样子，图片里框起来的地方就是我们填写的「虚拟路径」：

![给你免费加个「8百万TB」的硬盘，你猜能存多少东西？](https://p6.toutiaoimg.com/origin/tos-cn-i-qvj2lq49k0/6cfe0b61854a48b09f8ddccd4d398149?from=pc)

可移动、可下载、可重命名：

![给你免费加个「8百万TB」的硬盘，你猜能存多少东西？](https://p6.toutiaoimg.com/origin/tos-cn-i-qvj2lq49k0/32ee1346bfd74c8cb615985ab221c1e8?from=pc)

资源还可在线观看：

![给你免费加个「8百万TB」的硬盘，你猜能存多少东西？](https://p6.toutiaoimg.com/origin/tos-cn-i-qvj2lq49k0/62fb98a69455466e99e747504a417690?from=pc)

而当你把多个网盘都配置好，你就能在「127.0.0.1:5244」这个网页内随便访问了，比如我配置了阿里云盘、蓝奏云、123网盘和夸克网盘，访问效果如下：

![给你免费加个「8百万TB」的硬盘，你猜能存多少东西？](https://p6.toutiaoimg.com/origin/tos-cn-i-qvj2lq49k0/d8f839d9f97e4316a559043ccca6ecc2?from=pc)

**RaiDrive**

这时还只是浏览器里操作，想映射本地，还得请出评论区出镜率最高的 RaiDrive。

下载安装，打开 RaiDrive 后，按照提示去右上角找「Add」：

![给你免费加个「8百万TB」的硬盘，你猜能存多少东西？](https://p6.toutiaoimg.com/origin/tos-cn-i-qvj2lq49k0/1d00459f70ee4fba92e446ddc619bdb8?from=pc)

然后在「NAS」处找到「WebDAV」协议，给你挂载的盘符选个名，比如我选的是「L」，输入链接「127.0.0.1:5244/dav」，输入账号、密码，最后点击「OK」。

![给你免费加个「8百万TB」的硬盘，你猜能存多少东西？](https://p6.toutiaoimg.com/origin/tos-cn-i-qvj2lq49k0/3927ac1e4f5942e9bd0f38f85570d4c5?from=pc)

如果你不知道怎么搞，像我上面这张图配置即可，至于账号密码哪里找？去 Alist 管理后台的「后端」处找，密码每个人不一样，大家可别照抄了：

![给你免费加个「8百万TB」的硬盘，你猜能存多少东西？](https://p6.toutiaoimg.com/origin/tos-cn-i-qvj2lq49k0/20901db3402244ef9a8841104bf4eb11?from=pc)

当你做好了这些，再打开「我的电脑」，会发现有个「网络磁盘 L」：

![给你免费加个「8百万TB」的硬盘，你猜能存多少东西？](https://p6.toutiaoimg.com/origin/tos-cn-i-qvj2lq49k0/fbd41732fa534306a165c00f6c413a24?from=pc)

打开你会发现有 4 个文件夹，分别是阿里云盘、蓝奏云、夸克网盘和 123 盘，怎么操作就看你的了：

![给你免费加个「8百万TB」的硬盘，你猜能存多少东西？](https://p6.toutiaoimg.com/origin/tos-cn-i-qvj2lq49k0/65a5a27df262480297f141ab4ced2239?from=pc)

感受一下，你的电脑磁盘第一次出现以 EB 为单位的容量是什么感觉，也不是很大，1EB 也就等于 100 万 TB 吧，不管实际有多少，看着就带劲，想想看这里面能住多少个小姐姐。。。

不过大家别被这 8EB 迷住了眼，你配置了多少网盘，有多少容量，就能挂多少，但等你挂载完，就知道和你电脑合二为一的网盘到底有多方便了。

**结语**

把网盘挂载到本地，图的就是个方便，如果你没有把网盘挂到本地的需求，也可以利用 Alist 实现多网盘管理，一个网页就能查看所有网盘的资源。

具体的配置攻略，建议大家去看看 Alist 的官方文档，所有网盘的配置需求，包括那个提取阿里云盘移动端 token，文档里都有。

下一篇

[### 技术博客](https://i.plbear.com/post/ji-zhu-bo-ke/)
