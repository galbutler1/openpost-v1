"""
ingest.py — Download reels and compute performance scores.
Uses instaloader for Instagram, yt-dlp for TikTok.
"""

from __future__ import annotations

import urllib.request
from pathlib import Path

import instaloader
import yt_dlp

from config import VIDEOS_DIR
from models import Video, VideoMetadata


# ---------------------------------------------------------------------------
# Performance score
# ---------------------------------------------------------------------------

def _compute_performance_score(video: VideoMetadata, all_videos: list[VideoMetadata]) -> float:
    if not all_videos:
        return 50.0

    avg_views    = max(1, sum(v.view_count    for v in all_videos) / len(all_videos))
    avg_likes    = max(1, sum(v.like_count    for v in all_videos) / len(all_videos))
    avg_comments = max(1, sum(v.comment_count for v in all_videos) / len(all_videos))
    avg_shares   = max(1, sum(v.repost_count  for v in all_videos) / len(all_videos))

    def ratio(val: int, avg: float) -> float:
        return min(val / avg, 2.0)

    raw = (
        ratio(video.view_count,    avg_views)    * 0.40
        + ratio(video.like_count,  avg_likes)    * 0.25
        + ratio(video.comment_count, avg_comments) * 0.20
        + ratio(video.repost_count, avg_shares)  * 0.15
    )
    return round(min(raw / 2.0 * 100, 100.0), 1)


# ---------------------------------------------------------------------------
# Instagram via instaloader
# ---------------------------------------------------------------------------

def _download_instagram(username: str, n: int) -> list[Video]:
    L = instaloader.Instaloader(
        download_videos=False,
        download_video_thumbnails=False,
        download_geotags=False,
        download_comments=False,
        save_metadata=False,
        quiet=True,
    )

    print(f"Fetching posts for @{username}...")
    profile = instaloader.Profile.from_username(L.context, username)

    posts = []
    for post in profile.get_posts():
        if post.is_video:
            posts.append(post)
        if len(posts) >= max(n * 2, 30):
            break

    # Sort most recent first, take n
    posts.sort(key=lambda p: p.date, reverse=True)
    posts = posts[:n]

    all_meta = [
        VideoMetadata(
            view_count=post.video_view_count or 0,
            like_count=post.likes or 0,
            comment_count=post.comments or 0,
            repost_count=0,
            upload_date=post.date.strftime("%Y%m%d"),
        )
        for post in posts
    ]

    videos: list[Video] = []
    for post, meta in zip(posts, all_meta):
        video_id = post.shortcode
        out_path = VIDEOS_DIR / f"{video_id}.mp4"
        json_path = VIDEOS_DIR / f"{video_id}.json"

        if not out_path.exists():
            print(f"  Downloading {video_id}...")
            try:
                urllib.request.urlretrieve(post.video_url, str(out_path))
            except Exception as e:
                print(f"  [warn] Failed to download {video_id}: {e}")
                continue

        json_path.write_text(meta.model_dump_json(indent=2))
        perf = _compute_performance_score(meta, all_meta)

        videos.append(Video(
            video_id=video_id,
            file_path=str(out_path),
            metadata=meta,
            performance_score=perf,
        ))
        print(f"  {video_id} — views: {meta.view_count:,}  likes: {meta.like_count:,}  perf: {perf}")

    return videos


# ---------------------------------------------------------------------------
# TikTok via yt-dlp
# ---------------------------------------------------------------------------

def _download_tiktok(profile_url: str, n: int) -> list[Video]:
    extract_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "playlistend": max(n * 2, 30),
    }

    all_infos: list[dict] = []
    with yt_dlp.YoutubeDL(extract_opts) as ydl:
        result = ydl.extract_info(profile_url, download=False)
        if result is None:
            raise RuntimeError("yt-dlp returned no data.")
        entries = result.get("entries") or [result]
        for entry in entries:
            if entry:
                all_infos.append(entry)

    all_infos.sort(key=lambda x: x.get("upload_date") or "", reverse=True)
    selected = all_infos[:n]

    all_meta = [
        VideoMetadata(
            view_count=info.get("view_count") or 0,
            like_count=info.get("like_count") or 0,
            comment_count=info.get("comment_count") or 0,
            repost_count=info.get("repost_count") or info.get("share_count") or 0,
            upload_date=info.get("upload_date") or "",
        )
        for info in selected
    ]

    videos: list[Video] = []
    for info, meta in zip(selected, all_meta):
        video_id = info.get("id") or info.get("display_id") or str(len(videos))
        out_path = VIDEOS_DIR / f"{video_id}.mp4"
        json_path = VIDEOS_DIR / f"{video_id}.json"

        if not out_path.exists():
            url = info.get("webpage_url") or info.get("url")
            if not url:
                continue
            dl_opts = {
                "outtmpl": str(VIDEOS_DIR / f"{video_id}.%(ext)s"),
                "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best",
                "merge_output_format": "mp4",
                "quiet": True,
            }
            with yt_dlp.YoutubeDL(dl_opts) as ydl:
                try:
                    ydl.download([url])
                except Exception as e:
                    print(f"  [warn] Could not download {video_id}: {e}")
                    continue

        json_path.write_text(meta.model_dump_json(indent=2))
        perf = _compute_performance_score(meta, all_meta)

        videos.append(Video(
            video_id=video_id,
            file_path=str(out_path),
            metadata=meta,
            performance_score=perf,
        ))

    return videos


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def download_reels(profile_url: str, n: int) -> list[Video]:
    if "instagram.com" in profile_url:
        # Extract username from URL or treat as username directly
        username = profile_url.rstrip("/").split("/")[-1].lstrip("@")
        if not username or username in ("reels", "stories"):
            parts = profile_url.rstrip("/").split("/")
            username = [p for p in parts if p and p not in ("https:", "www.instagram.com", "reels", "stories")][0]
        return _download_instagram(username, n)
    else:
        return _download_tiktok(profile_url, n)
