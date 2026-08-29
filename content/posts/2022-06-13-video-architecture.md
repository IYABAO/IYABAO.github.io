---
title: "招聘视频功能架构设计：视频上传、转码与播放的完整链路"
date: 2022-06-13T16:00:00+08:00
draft: false
tags: ["架构设计", "视频处理", "FFmpeg", "阿里云", "PHP", "Go"]
categories: ["架构设计"]
summary: "招聘平台视频功能的完整架构设计，涵盖前端上传、服务端转码、CDN 分发、播放器适配，以及大文件上传、转码队列、水印处理等工程实践。"
---

2022年招聘平台加了视频功能——企业可以发布企业宣传视频，求职者可以上传自我介绍视频。视频处理和图片完全不同，涉及上传、转码、存储、分发等多个环节。今天把整个架构设计和工程实践分享出来。

## 一、需求分析

1. **企业端**：上传企业宣传视频，展示在企业主页和职位详情页
2. **求职者端**：上传自我介绍视频，展示在简历中
3. **视频规格**：支持 MP4/MOV/AVI 等常见格式，最大 500MB
4. **播放体验**：多清晰度（标清/高清）、自适应码率、首屏快速播放
5. **安全**：视频防盗链、防止下载

## 二、整体架构

```text
前端 → 分片上传 → 上传服务 → OSS 源文件
                              ↓
                        转码队列（RabbitMQ）
                              ↓
                        转码服务（FFmpeg）
                              ↓
                        OSS 转码文件 → CDN 分发 → 播放器
```

- **上传**：前端分片上传到 OSS，支持断点续传
- **转码**：上传完成后发消息到队列，转码服务消费，用 FFmpeg 转成多清晰度 MP4 + HLS
- **存储**：源文件和转码文件都存 OSS，生命周期管理自动删除源文件
- **分发**：CDN 加速播放，防盗链
- **播放**：前端用 video.js 或 hls.js，支持 HLS 自适应码率

## 三、上传设计

### 3.1 分片上传

大文件（500MB）不能一次性上传，用分片上传：

```javascript
// 前端：分片上传
const chunkSize = 5 * 1024 * 1024; // 5MB一片
const chunks = Math.ceil(file.size / chunkSize);

for (let i = 0; i < chunks; i++) {
    const start = i * chunkSize;
    const end = Math.min(start + chunkSize, file.size);
    const chunk = file.slice(start, end);
    
    // 上传分片到 OSS（用 STS 临时授权）
    await uploadChunk(fileId, i, chunk);
}

// 所有分片上传完成，通知服务端合并
await mergeChunks(fileId, chunks);
```

OSS 的分片上传（Multipart Upload）原生支持，前端用 STS 临时授权直传，不经过业务服务器，节省带宽。

### 3.2 断点续传

记录已上传的分片，刷新页面后跳过已上传的：

```javascript
// 查询已上传的分片
const uploaded = await getUploadedChunks(fileId);
for (let i = 0; i < chunks; i++) {
    if (uploaded.includes(i)) continue; // 跳过已上传的
    await uploadChunk(fileId, i, getChunk(file, i));
}
```

用文件 MD5 作为 fileId，同一个文件多次上传能识别出来，实现秒传（服务端已存在则直接返回）。

## 四、转码设计

### 4.1 转码队列

上传完成后发消息到 RabbitMQ，转码服务消费：

```php
// 上传完成后发消息
Yii::$app->queue->push(new VideoTranscodeJob([
    'video_id' => $video->id,
    'source_url' => $video->source_url,
]));
```

转码服务用 Go 写的，并发处理能力强：

```go
func (s *TranscodeService) Consume(msg []byte) error {
    var job VideoTranscodeJob
    json.Unmarshal(msg, &job)
    
    // 1. 下载源文件
    sourcePath, _ := s.download(job.SourceURL)
    
    // 2. 获取视频信息
    info, _ := s.probe(sourcePath)
    
    // 3. 转码多清晰度
    for _, quality := range []string{"480p", "720p"} {
        outputPath := fmt.Sprintf("/tmp/transcode_%s_%s.mp4", job.VideoID, quality)
        s.transcode(sourcePath, outputPath, quality)
        s.upload(outputPath, job.VideoID, quality)
    }
    
    // 4. 生成 HLS
    s.generateHLS(sourcePath, job.VideoID)
    
    // 5. 截图封面
    s.screenshot(sourcePath, job.VideoID)
    
    // 6. 更新状态
    s.updateStatus(job.VideoID, "completed")
    return nil
}
```

### 4.2 FFmpeg 转码

```bash
# 转 720p MP4
ffmpeg -i input.mp4 -s 1280x720 -c:v libx264 -preset medium -crf 23 -c:a aac -b:a 128k output_720p.mp4

# 转 HLS（m3u8 + ts分片）
ffmpeg -i input.mp4 -c:v libx264 -c:a aac -hls_time 10 -hls_list_size 0 -f hls output.m3u8

# 截图封面（第5秒）
ffmpeg -i input.mp4 -ss 5 -vframes 1 -q:v 2 cover.jpg

# 加水印
ffmpeg -i input.mp4 -i logo.png -filter_complex "overlay=10:10" output.mp4
```

转码是 CPU 密集型任务，转码服务要单独部署，不能和 Web 服务混部。用独立的转码服务器集群，根据队列长度自动扩缩容。

### 4.3 转码进度

转码时间长（几分钟到几十分钟），要实时更新进度：

```go
// FFmpeg 输出进度，解析后更新
ffmpeg -i input.mp4 ... -progress pipe:1 2>&1 | grep out_time_ms
```

前端轮询或 WebSocket 获取转码进度，展示进度条。

## 五、播放设计

### 5.1 播放器

用 hls.js 播放 HLS，支持自适应码率：

```javascript
if (Hls.isSupported()) {
    const hls = new Hls();
    hls.loadSource('https://cdn.example.com/video/123/playlist.m3u8');
    hls.attachMedia(video);
    hls.on(Hls.Events.MANIFEST_PARSED, () => video.play());
} else if (video.canPlayType('application/vnd.apple.mpegurl')) {
    // Safari 原生支持 HLS
    video.src = 'https://cdn.example.com/video/123/playlist.m3u8';
}
```

HLS 的优势：
- 自适应码率，根据网络自动切换清晰度
- 分片传输，首屏加载快
- CDN 缓存友好，ts 分片可以长期缓存

### 5.2 防盗链

CDN 配置 Referer 防盗链和时间戳防盗链：

```php
// 生成带签名的播放地址
function generateVideoUrl($videoId, $expire = 3600) {
    $path = "/video/{$videoId}/playlist.m3u8";
    $timestamp = time() + $expire;
    $sign = md5("{$path}{$timestamp}" . CDN_KEY);
    return "https://cdn.example.com{$path}?t={$timestamp}&sign={$sign}";
}
```

CDN 校验签名和过期时间，防止链接被盗用。

## 六、踩坑经验

**1. 转码服务 OOM**：大视频转码时 FFmpeg 内存占用高，转码服务器内存不够会 OOM。限制并发转码数，大视频优先用低分辨率转码。

**2. 上传超时**：500MB 文件上传时间长，Nginx 默认超时时间不够。调大 `client_max_body_size` 和 `proxy_read_timeout`，或者用 OSS 直传绕过 Nginx。

**3. 跨域问题**：视频分片跨域，CDN 要配置 CORS 头，否则 hls.js 加载失败。

**4. 首屏黑屏**：HLS 第一个分片加载慢导致首屏黑屏。优化：封面图先展示、预加载第一个分片、CDN 预热热门视频。

**5. 转码失败重试**：网络抖动导致下载源文件失败，转码失败。加重试机制，失败后重新入队，最多重试 3 次。

## 七、总结

招聘视频功能的架构设计要点：

1. **上传**：分片上传 + 断点续传 + OSS 直传，支持大文件
2. **转码**：FFmpeg 多清晰度 + HLS，队列异步处理，转码服务独立部署
3. **存储**：OSS 存源文件和转码文件，生命周期管理自动清理
4. **分发**：CDN 加速 + 防盗链，保证播放速度和安全
5. **播放**：HLS 自适应码率 + 封面预加载，优化首屏体验
6. **监控**：上传成功率、转码成功率、播放流畅度，全链路监控

视频功能的技术栈比图文复杂很多，涉及前端、后端、运维、多媒体处理多个领域。但核心思路还是异步解耦——上传、转码、分发各环节解耦，用队列连接，任何一环出问题都不影响其他环节。
