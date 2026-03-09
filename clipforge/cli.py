"""CLI interface for ClipForge."""

from pathlib import Path

import typer
from rich.console import Console

app = typer.Typer(help="ClipForge — turn existing videos into new short-form content")
console = Console()


@app.command()
def process(
    input_dir: Path = typer.Argument(..., help="Directory containing source videos"),
    output_dir: Path = typer.Option("./output", "--output", "-o", help="Output directory for clips and library"),
):
    """Process videos: detect scenes, separate audio, transcribe, analyze."""
    from clipforge.pipeline import run_pipeline

    if not input_dir.exists():
        console.print(f"[red]Input directory not found: {input_dir}[/]")
        raise typer.Exit(1)

    run_pipeline(input_dir, output_dir)


@app.command()
def remix(
    library: Path = typer.Argument(..., help="Path to clip_library.json"),
    output_dir: Path = typer.Option("./output/remixes", "--output", "-o", help="Output directory for remixes"),
    count: int = typer.Option(5, "--count", "-n", help="Number of remixes to generate"),
    template: str = typer.Option(None, "--template", "-t", help="Template name (hook_montage, reordered_narrative, highlight_reel, hook_swap)"),
    no_beat_sync: bool = typer.Option(False, "--no-beat-sync", help="Disable beat-synced cuts"),
):
    """Generate remix variations from a processed clip library."""
    from clipforge.workers.remixer import generate_remixes, TEMPLATES

    if not library.exists():
        console.print(f"[red]Library not found: {library}[/]")
        raise typer.Exit(1)

    if template and template not in TEMPLATES:
        console.print(f"[red]Unknown template: {template}[/]")
        console.print(f"Available: {', '.join(TEMPLATES.keys())}")
        raise typer.Exit(1)

    console.print(f"[bold]Generating {count} remixes...[/]")
    outputs = generate_remixes(
        library_path=library,
        output_dir=Path(output_dir),
        template_name=template,
        count=count,
        beat_sync=not no_beat_sync,
    )
    console.print(f"\n[bold green]Done![/] Generated {len(outputs)} remixes in {output_dir}")
    for o in outputs:
        console.print(f"  {o.name}")


@app.command()
def download(
    username: str = typer.Argument(..., help="Instagram username to download videos from"),
    output_dir: Path = typer.Option("./input_videos", "--output", "-o", help="Output directory for downloaded videos"),
    limit: int = typer.Option(0, "--limit", "-l", help="Max videos to download (0 = all)"),
):
    """Download all videos from an Instagram account."""
    from clipforge.workers.downloader import download_account

    output_dir.mkdir(parents=True, exist_ok=True)
    console.print(f"[bold]Downloading videos from @{username}...[/]")
    count = download_account(username, output_dir, limit=limit)
    console.print(f"\n[bold green]Done![/] Downloaded {count} videos to {output_dir}")


@app.command()
def autoremix(
    library: Path = typer.Argument(..., help="Path to clip_library.json"),
    output_dir: Path = typer.Option("./output/remixes", "--output", "-o", help="Output directory for remixes"),
    max_remixes: int = typer.Option(0, "--max", "-n", help="Max remixes to generate (0 = one per source video)"),
    cut_rate: float = typer.Option(0.45, "--cut-rate", "-c", help="How often to cut to supplemental on beats (0-1)"),
):
    """Fully automated: generate anchor-based remixes from a clip library. No manual input needed."""
    from clipforge.workers.anchor_remixer import generate_all_remixes

    if not library.exists():
        console.print(f"[red]Library not found: {library}[/]")
        raise typer.Exit(1)

    outputs = generate_all_remixes(
        library_path=library,
        output_dir=Path(output_dir),
        cut_probability=cut_rate,
        max_remixes=max_remixes,
    )
    console.print(f"\n[bold green]Done![/] Generated {len(outputs)} remixes in {output_dir}")
    for o in outputs:
        console.print(f"  {o.name}")


if __name__ == "__main__":
    app()
