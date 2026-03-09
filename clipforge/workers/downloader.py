"""Download videos from an Instagram account using instaloader."""

import shutil
from pathlib import Path

import instaloader
from rich.console import Console

console = Console()


def download_account(username: str, output_dir: Path, limit: int = 0) -> int:
    """Download all video posts from an Instagram account.

    Args:
        username: Instagram username (without @)
        output_dir: Directory to save videos to
        limit: Max number of videos to download (0 = all)

    Returns:
        Number of videos downloaded
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    L = instaloader.Instaloader(
        download_videos=True,
        download_video_thumbnails=False,
        download_geotags=False,
        download_comments=False,
        save_metadata=False,
        compress_json=False,
        post_metadata_txt_pattern="",
        filename_pattern="{shortcode}",
    )

    # Optional: login for private accounts or to avoid rate limits
    # L.login("your_username", "your_password")

    try:
        profile = instaloader.Profile.from_username(L.context, username)
    except instaloader.exceptions.ProfileNotExistsException:
        console.print(f"[red]Profile @{username} not found.[/]")
        return 0

    console.print(f"[dim]Found @{username} — {profile.mediacount} posts[/]")

    count = 0
    for post in profile.get_posts():
        # Only download videos (Reels, video posts)
        if not post.is_video:
            continue

        console.print(f"  [dim]Downloading {post.shortcode}...[/]")

        try:
            L.download_post(post, target=str(output_dir))
            count += 1
            console.print(f"  [green]✓ {post.shortcode}[/] ({count})")
        except Exception as e:
            console.print(f"  [yellow]⚠ Skipped {post.shortcode}: {e}[/]")
            continue

        if limit and count >= limit:
            break

    # instaloader saves with extra files — clean up non-video files
    for f in output_dir.iterdir():
        if f.suffix not in {".mp4", ".mov", ".avi", ".mkv", ".webm"}:
            f.unlink(missing_ok=True)

    console.print(f"\n[bold]{count} videos downloaded to {output_dir}[/]")
    return count
