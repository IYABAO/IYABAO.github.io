#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
博客图片上传工具（GitHub + jsDelivr CDN 方案）

功能：
1. 将指定图片复制到 static/images/ 目录
2. 自动重命名为 日期-序号-原名 格式，避免重名
3. 输出 jsDelivr CDN 链接和 Hugo 短代码，方便直接粘贴到文章中

用法：
  python scripts/upload-image.py <图片路径> [自定义名称]
  
示例：
  python scripts/upload-image.py C:/Users/xxx/Pictures/screenshot.png
  python scripts/upload-image.py C:/Users/xxx/Pictures/screenshot.png 架构图
  
输出：
  ✅ 图片已复制到: static/images/2026-09-09-001-架构图.png
  🌐 CDN 链接: https://cdn.jsdelivr.net/gh/IYABAO/IYABAO.github.io@master/static/images/2026-09-09-001-架构图.png
  📝 Hugo 短代码: {{< img src="2026-09-09-001-架构图.png" alt="架构图" >}}
"""

import os
import sys
import shutil
from datetime import datetime
from pathlib import Path

# 博客根目录（脚本在 scripts/ 下，所以上一级是根目录）
BLOG_ROOT = Path(__file__).parent.parent
IMAGES_DIR = BLOG_ROOT / "static" / "images"

# jsDelivr CDN 基础 URL
CDN_BASE = "https://cdn.jsdelivr.net/gh/IYABAO/IYABAO.github.io@master/static/images/"


def get_next_sequence(date_str: str) -> int:
    """获取指定日期的下一个序号"""
    if not IMAGES_DIR.exists():
        return 1
    
    existing = list(IMAGES_DIR.glob(f"{date_str}-*"))
    if not existing:
        return 1
    
    max_seq = 0
    for f in existing:
        try:
            # 文件名格式: 2026-09-09-001-xxx.png
            seq_part = f.stem.split("-")[3]
            seq = int(seq_part)
            if seq > max_seq:
                max_seq = seq
        except (IndexError, ValueError):
            continue
    
    return max_seq + 1


def sanitize_filename(name: str) -> str:
    """清理文件名中的非法字符"""
    # 替换非法字符
    invalid = '<>:"/\\|?*'
    for ch in invalid:
        name = name.replace(ch, '-')
    # 替换空格为连字符
    name = name.replace(' ', '-')
    # 限制长度
    if len(name) > 50:
        name = name[:50]
    return name


def main():
    if len(sys.argv) < 2:
        print("❌ 用法: python scripts/upload-image.py <图片路径> [自定义名称]")
        print("示例: python scripts/upload-image.py C:/Users/xxx/Pictures/screenshot.png 架构图")
        sys.exit(1)
    
    src_path = Path(sys.argv[1])
    custom_name = sys.argv[2] if len(sys.argv) > 2 else None
    
    # 检查源文件
    if not src_path.exists():
        print(f"❌ 文件不存在: {src_path}")
        sys.exit(1)
    
    if not src_path.is_file():
        print(f"❌ 不是文件: {src_path}")
        sys.exit(1)
    
    # 检查文件扩展名
    ext = src_path.suffix.lower()
    valid_exts = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.bmp'}
    if ext not in valid_exts:
        print(f"⚠️  警告: 文件扩展名 {ext} 不是常见图片格式，但仍会继续处理")
    
    # 确保 images 目录存在
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    
    # 生成新文件名
    date_str = datetime.now().strftime("%Y-%m-%d")
    seq = get_next_sequence(date_str)
    
    if custom_name:
        name_part = sanitize_filename(custom_name)
    else:
        name_part = sanitize_filename(src_path.stem)
    
    new_filename = f"{date_str}-{seq:03d}-{name_part}{ext}"
    dest_path = IMAGES_DIR / new_filename
    
    # 复制文件
    shutil.copy2(src_path, dest_path)
    
    # 输出结果
    cdn_url = f"{CDN_BASE}{new_filename}"
    shortcode = f'{{{{< img src="{new_filename}" alt="{name_part}" >}}}}'
    
    print(f"\n✅ 图片已复制到: static/images/{new_filename}")
    print(f"📁 本地路径: {dest_path}")
    print(f"📦 文件大小: {dest_path.stat().st_size / 1024:.1f} KB")
    print(f"\n🌐 CDN 链接: {cdn_url}")
    print(f"📝 Hugo 短代码: {shortcode}")
    print(f"\n💡 提示: 将短代码粘贴到文章 Markdown 中即可使用")
    print(f"💡 提示: 推送代码到 GitHub 后，jsDelivr CDN 会自动生效（可能需要几分钟缓存刷新）")
    
    # 如果需要刷新 jsDelivr 缓存
    print(f"\n🔄 如需立即刷新 CDN 缓存，访问:")
    print(f"   https://purge.jsdelivr.net/gh/IYABAO/IYABAO.github.io@master/static/images/{new_filename}")


if __name__ == "__main__":
    main()
