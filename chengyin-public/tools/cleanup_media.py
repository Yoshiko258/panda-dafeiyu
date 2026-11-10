# -*- coding: utf-8 -*-
"""清理可以再生的媒体文件。

默认 dry-run，只打印会删什么、省多少；加 --apply 才真删。

策略（都可改）：
    火山自拍 out/        保留最近 SELFIE_KEEP 张
    ddsp 翻唱 cache/     保留最近 CACHE_DAYS 天
    ddsp 翻唱 runs/      保留最近 RUNS_KEEP 次
    私聊入站图片         保留最近 7 天（插件也会清，这里兜底）
    面板生成图           保留最近 30 天

用法:
    python tools/cleanup_media.py            # 预览
    python tools/cleanup_media.py --apply    # 执行
"""

from __future__ import annotations

import argparse
import os
import sys
import time

ROOT = r"D:\chengyin"
DATA = os.path.join(ROOT, "astrbot", "data", "plugin_data")

SELFIE_KEEP = 20      # 保留最近多少张自拍
CACHE_DAYS = 7        # ddsp 音频缓存保留天数
RUNS_KEEP = 2         # ddsp 翻唱中间产物保留次数
INBOUND_DAYS = 7      # 私聊入站图片
PHOTO_DAYS = 30       # 面板生成图
TMP_DAYS = 14         # .tmp 里的临时试验产物

SELFIE_OUT = os.path.join(DATA, "astrbot_plugin_volc_selfie", "out")
DDSP_CACHE = os.path.join(DATA, "astrbot_plugin_ddsp_cover", "cache")
DDSP_RUNS = os.path.join(DATA, "astrbot_plugin_ddsp_cover", "runs")
INBOUND = os.path.join(
    DATA, "astrbot_plugin_private_companion", "private_inbound_images")
PHOTOS = os.path.join(
    DATA, "astrbot_plugin_private_companion", "generated_photos")


def walk_files(path: str) -> list[tuple[float, int, str]]:
    """列出目录下所有文件 (mtime, size, path)。"""
    out = []
    if not os.path.isdir(path):
        return out
    for root, _, files in os.walk(path):
        for name in files:
            full = os.path.join(root, name)
            try:
                st = os.stat(full)
            except OSError:
                continue
            out.append((st.st_mtime, st.st_size, full))
    return out


def keep_newest(files: list[tuple[float, int, str]], keep: int) -> list[tuple[float, int, str]]:
    """按修改时间倒序，前 keep 个保留，其余作为删除候选。"""
    ordered = sorted(files, key=lambda item: item[0], reverse=True)
    return ordered[keep:]


def older_than(files: list[tuple[float, int, str]], days: float) -> list[tuple[float, int, str]]:
    """早于 days 天的文件。"""
    cutoff = time.time() - days * 86400
    return [item for item in files if item[0] < cutoff]


def keep_newest_dirs(path: str, keep: int) -> list[str]:
    """保留最近 keep 个子目录，返回其余目录路径。"""
    if not os.path.isdir(path):
        return []
    entries = []
    for name in os.listdir(path):
        full = os.path.join(path, name)
        if os.path.isdir(full):
            try:
                entries.append((os.stat(full).st_mtime, full))
            except OSError:
                continue
    entries.sort(reverse=True)
    return [full for _, full in entries[keep:]]


def plan() -> list[tuple[str, list[tuple[float, int, str]], list[str]]]:
    """算出每个目标的删除计划：(标签, 要删的文件, 要删的整目录)。"""
    groups: list[tuple[str, list[tuple[float, int, str]], list[str]]] = []

    groups.append((
        f"火山自拍 out/（保留最近 {SELFIE_KEEP} 张）",
        keep_newest(walk_files(SELFIE_OUT), SELFIE_KEEP),
        [],
    ))
    groups.append((
        f"ddsp 音频缓存（保留最近 {CACHE_DAYS} 天）",
        older_than(walk_files(DDSP_CACHE), CACHE_DAYS),
        [],
    ))
    runs_dirs = keep_newest_dirs(DDSP_RUNS, RUNS_KEEP)
    runs_files = []
    for d in runs_dirs:
        runs_files.extend(walk_files(d))
    groups.append((
        f"ddsp 翻唱中间产物（保留最近 {RUNS_KEEP} 次）",
        runs_files,
        runs_dirs,
    ))
    groups.append((
        f"私聊入站图片（保留最近 {INBOUND_DAYS} 天）",
        older_than(walk_files(INBOUND), INBOUND_DAYS),
        [],
    ))
    groups.append((
        f"面板生成图（保留最近 {PHOTO_DAYS} 天）",
        older_than(walk_files(PHOTOS), PHOTO_DAYS),
        [],
    ))
    tmp_dir = os.path.join(ROOT, ".tmp")
    if os.path.isdir(tmp_dir):
        groups.append((
            f".tmp 临时产物（保留最近 {TMP_DAYS} 天）",
            older_than(walk_files(tmp_dir), TMP_DAYS),
            [],
        ))
    return groups


def main() -> int:
    ap = argparse.ArgumentParser(description="清理可再生媒体文件")
    ap.add_argument("--apply", action="store_true", help="真的删除，默认只预览")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    total_files = total_bytes = 0
    for label, files, dirs in plan():
        size = sum(item[1] for item in files)
        if not files and not dirs:
            print(f"  [跳过] {label}：没有要清的")
            continue
        print(f"  [{label}]")
        for mtime, fsize, full in sorted(files, key=lambda i: i[1], reverse=True)[:5]:
            rel = os.path.relpath(full, ROOT)
            print(f"    {fsize/1024/1024:6.1f} MB  {rel}")
        if len(files) > 5:
            print(f"    … 另有 {len(files)-5} 个文件")
        if dirs:
            print(f"    整个目录 {len(dirs)} 个：{[os.path.basename(d) for d in dirs[:3]]}")
        print(f"    小计 {len(files)} 个文件 / {size/1024/1024:.1f} MB")
        total_files += len(files)
        total_bytes += size
        if args.apply:
            for _, _, full in files:
                try:
                    os.remove(full)
                except OSError as exc:
                    print(f"    删除失败 {os.path.relpath(full, ROOT)}: {exc}")
            for d in dirs:
                for mtime, fsize, full in walk_files(d):
                    try:
                        os.remove(full)
                    except OSError:
                        pass
                try:
                    os.rmdir(d)
                except OSError:
                    pass  # 目录非空就留着，下次再清

    print()
    if args.apply:
        print(f"已清理 {total_files} 个文件，释放约 {total_bytes/1024/1024:.1f} MB")
    else:
        print(f"可清理 {total_files} 个文件，约 {total_bytes/1024/1024:.1f} MB（加 --apply 执行）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
