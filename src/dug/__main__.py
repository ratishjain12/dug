import sys
from pathlib import Path

import click

from .config import load_config, save_config, set_config_value, get_dug_dir, DEFAULTS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

LANG_EXTENSIONS = {
    "python": [".py"],
    "java": [".java"],
    "typescript": [".ts", ".tsx"],
    "javascript": [".js", ".jsx"],
}


def _detect_languages(root: Path) -> list[str]:
    detected = []
    for lang, exts in LANG_EXTENSIONS.items():
        for ext in exts:
            if any(root.rglob(f"*{ext}")):
                detected.append(lang)
                break
    return detected or ["python"]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

@click.group(
    invoke_without_command=True,
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
@click.pass_context
def cli(ctx):
    """dug — dig into any bug with full codebase context."""
    if ctx.invoked_subcommand is None:
        if ctx.args:
            ctx.invoke(query, bug_input=" ".join(ctx.args))
        else:
            click.echo(ctx.get_help())


@cli.command()
def init():
    """First-time setup — wizard + full index build."""
    click.echo("\nWelcome to dug.\n")

    # Embedding mode
    click.echo("Embedding mode:")
    click.echo("  1. Local  — no API key, runs on CPU  (recommended)")
    click.echo("  2. OpenAI — needs API key, faster")
    choice = click.prompt("\n>", default="1").strip()

    cfg = load_config()

    if choice == "2":
        api_key = click.prompt("OpenAI API key").strip()
        cfg["embedding_mode"] = "openai"
        cfg["api_key"] = api_key
        click.echo("\n✓ Using OpenAI embeddings.")
    else:
        cfg["embedding_mode"] = "local"
        cfg["api_key"] = None
        click.echo("\n✓ Using local embeddings. No API key needed.")

    # Language detection
    root = Path.cwd()
    detected = _detect_languages(root)
    click.echo(f"\nLanguages detected: {', '.join(detected)}")
    cfg["languages"] = detected

    # Ignore paths
    click.echo(f"Ignore paths: {', '.join(cfg['ignore_paths'])}")

    save_config(cfg)
    click.echo(f"\nConfig saved to {get_dug_dir() / 'config.json'}")

    # Build index
    click.echo("\nStarting initial index...")
    try:
        from .indexer import run_init
        stats = run_init(root)
        files = stats["nodes"].get("FILE", 0)
        symbols = stats["nodes"].get("SYMBOL", 0)
        commits = stats["nodes"].get("COMMIT", 0)
        edges = stats["edges"]
        click.echo(f"  FILE nodes:   {files}")
        click.echo(f"  SYMBOL nodes: {symbols}")
        click.echo(f"  COMMIT nodes: {commits}")
        click.echo(f"  Total edges:  {edges}")
        click.echo("\n✓ dug is ready. Run: dug \"your error here\"")
    except Exception as e:
        click.echo(f"\n✗ Index failed: {e}", err=True)
        sys.exit(1)


@cli.command(name="query")
@click.argument("bug_input")
def query(bug_input):
    """Query the index with a bug or stack trace."""
    cfg = load_config()
    dug_dir = get_dug_dir()

    if not (dug_dir / "graph.json").exists():
        click.echo("No index found. Run: dug init", err=True)
        sys.exit(1)

    from .graph import CodeGraph
    graph = CodeGraph()
    graph.load(dug_dir / "graph.json")

    stats = graph.stats()
    click.echo(f"\n[dug] Graph loaded — {stats['nodes'].get('FILE', 0)} files, "
               f"{stats['nodes'].get('SYMBOL', 0)} symbols\n")

    # Phase 3 will add real hybrid search + prompt assembly
    click.echo("## Bug Report\n")
    click.echo(f"**Error:** {bug_input}\n")
    click.echo("*(Full retrieval and prompt assembly coming in Phase 3)*")


@cli.command()
@click.option("--changed-only", is_flag=True, help="Reindex only git-changed files.")
@click.option("--branch-switch", is_flag=True, hidden=True)
@click.option("--from", "from_ref", default=None, hidden=True)
@click.option("--to", "to_ref", default=None, hidden=True)
def update(changed_only, branch_switch, from_ref, to_ref):
    """Refresh the graph and index."""
    click.echo("Updating index...")
    try:
        from .indexer import run_init
        stats = run_init(Path.cwd())
        click.echo(f"✓ Done — {stats['nodes'].get('FILE', 0)} files indexed.")
    except Exception as e:
        click.echo(f"✗ Update failed: {e}", err=True)
        sys.exit(1)


@cli.command()
def watch():
    """Start background file watcher (Phase 4)."""
    click.echo("File watcher not yet implemented (Phase 4).")


@cli.command()
def solved():
    """Capture feedback after fixing a bug (Phase 5)."""
    click.echo("Feedback loop not yet implemented (Phase 5).")


@cli.command()
def stats():
    """Print graph stats."""
    dug_dir = get_dug_dir()
    if not (dug_dir / "graph.json").exists():
        click.echo("No index found. Run: dug init", err=True)
        sys.exit(1)

    from .graph import CodeGraph
    graph = CodeGraph()
    graph.load(dug_dir / "graph.json")
    s = graph.stats()
    click.echo("\nGraph stats:")
    for kind, count in s["nodes"].items():
        click.echo(f"  {kind}: {count}")
    click.echo(f"  Edges: {s['edges']}")


@cli.group()
def config():
    """Manage dug configuration."""


@config.command(name="set")
@click.argument("key")
@click.argument("value")
def config_set(key, value):
    """Set a config value. Example: dug config set embedding-mode openai"""
    key = key.replace("-", "_")
    set_config_value(key, value)
    click.echo(f"✓ {key} = {value}")


@config.command(name="show")
def config_show():
    """Show current config."""
    cfg = load_config()
    import json
    click.echo(json.dumps(cfg, indent=2))


if __name__ == "__main__":
    cli()
