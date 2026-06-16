import sys
from pathlib import Path

import click

from .config import load_config, save_config, set_config_value, get_dug_dir, DEFAULTS, find_repo_root


class DefaultToQueryGroup(click.Group):
    """Routes `dug "some error"` to the query command when first arg isn't a subcommand."""

    def parse_args(self, ctx, args):
        if args and not args[0].startswith("-") and args[0] not in self.commands:
            args = ["query"] + args
        return super().parse_args(ctx, args)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

LANG_EXTENSIONS = {
    "python": [".py"],
    "java": [".java"],
    "typescript": [".ts", ".tsx"],
    "javascript": [".js", ".jsx"],
}


def _detect_languages(root: Path, ignore_paths: list[str]) -> list[str]:
    detected = []
    for lang, exts in LANG_EXTENSIONS.items():
        for ext in exts:
            found = False
            for p in root.rglob(f"*{ext}"):
                parts = set(p.parts)
                if not any(ig in parts for ig in ignore_paths):
                    found = True
                    break
            if found:
                detected.append(lang)
    return detected or ["python"]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

@click.group(cls=DefaultToQueryGroup, invoke_without_command=True)
@click.pass_context
def cli(ctx):
    """dug — dig into any bug with full codebase context."""
    if ctx.invoked_subcommand is None:
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
    root = find_repo_root()
    detected = _detect_languages(root, cfg.get("ignore_paths", []))
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
        from .embeddings import get_embedder
        from .hooks import install_git_hooks, ensure_gitignore
        gi_status = ensure_gitignore(root)
        click.echo(f"  .gitignore: {gi_status}")
        embedder = get_embedder(cfg)
        stats = run_init(root, embedder=embedder)
        files   = stats["nodes"].get("FILE", 0)
        symbols = stats["nodes"].get("SYMBOL", 0)
        commits = stats["nodes"].get("COMMIT", 0)
        edges   = stats["edges"]
        chunks  = stats.get("chunks", 0)
        click.echo(f"  FILE nodes:   {files}")
        click.echo(f"  SYMBOL nodes: {symbols}")
        click.echo(f"  COMMIT nodes: {commits}")
        click.echo(f"  Total edges:  {edges}")
        click.echo(f"  Chunks embedded: {chunks}")

        # Install git hooks
        hook_results = install_git_hooks(root)
        if "error" not in hook_results:
            click.echo(f"\n  Git hooks:")
            for hook, status in hook_results.items():
                click.echo(f"    {hook}: {status}")

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
    from .embeddings import get_embedder
    from .vector_store import get_or_create_table
    from .retriever import hybrid_search
    from .verifier import verify_files
    from .prompt_builder import build_prompt
    from .git_context import get_git_history

    graph = CodeGraph()
    graph.load(dug_dir / "graph.json")

    embedder = get_embedder(cfg)
    table = get_or_create_table(dug_dir / "embeddings", cfg.get("embedding_mode", "local"))

    ranked, signals = hybrid_search(
        embedder, graph, table, bug_input,
        top_k=cfg.get("max_files_in_prompt", 5),
    )

    # Verify candidates actually contain extracted symbols / bug words
    root = find_repo_root()
    verified_paths = verify_files(
        [f.path for f in ranked], signals.get("symbols", []), root, bug_input
    )
    ranked = [f for f in ranked if f.path in verified_paths]

    git_commits = get_git_history(root, depth=cfg.get("git_history_depth", 50))

    prompt = build_prompt(bug_input, ranked, git_commits, signals)
    click.echo(prompt)

    # Save for `dug solved`
    from .history import save_last_query
    save_last_query(bug_input, [f.path for f in ranked], signals)


@cli.command()
@click.option("--changed-only", is_flag=True, help="Reindex only git-changed files.")
@click.option("--branch-switch", is_flag=True, hidden=True)
@click.option("--from", "from_ref", default="HEAD~1", hidden=True)
@click.option("--to", "to_ref", default="HEAD", hidden=True)
def update(changed_only, branch_switch, from_ref, to_ref):
    """Refresh the graph and index."""
    root = find_repo_root()
    try:
        if changed_only or branch_switch:
            from .indexer import update_changed_files
            result = update_changed_files(
                root, from_ref=from_ref, to_ref=to_ref
            )
            pruned  = result.get("pruned", [])
            updated = result.get("updated", [])
            skipped = result.get("skipped", [])
            if pruned:
                click.echo(f"  Pruned {len(pruned)} deleted file(s).")
            click.echo(f"✓ Updated {len(updated)} file(s), skipped {len(skipped)} unchanged.")
        else:
            click.echo("Rebuilding full index...")
            from .indexer import run_init
            from .hooks import ensure_gitignore
            ensure_gitignore(root)
            stats = run_init(root)
            click.echo(f"✓ Done — {stats['nodes'].get('FILE', 0)} files, "
                       f"{stats.get('chunks', 0)} chunks.")
    except Exception as e:
        click.echo(f"✗ Update failed: {e}", err=True)
        sys.exit(1)


@cli.command()
def watch():
    """Start background file watcher — reindexes on save (1.5s debounce)."""
    dug_dir = get_dug_dir()
    if not (dug_dir / "graph.json").exists():
        click.echo("No index found. Run: dug init first.", err=True)
        sys.exit(1)
    from .watcher import start_watch
    start_watch(Path.cwd())


@cli.command()
@click.option("--files", "-f", default=None,
              help="Comma-separated file paths that contained the fix.")
def solved(files):
    """Record which files fixed the last bug — improves future rankings."""
    from .history import load_last_query, record_resolved

    last = load_last_query()
    if not last:
        click.echo("No recent query found. Run: dug \"your error\" first.", err=True)
        sys.exit(1)

    click.echo(f"\nLast query: \"{last['bug_input']}\"")
    click.echo(f"Suggested files were:")
    for f in last.get("ranked_files", []):
        click.echo(f"  - {f}")

    if files:
        resolved = [f.strip() for f in files.split(",") if f.strip()]
    else:
        click.echo("\nWhich files actually contained the bug? (comma-separated paths)")
        click.echo("Press Enter to accept the suggestions above, or type new paths.")
        raw = click.prompt(">", default=",".join(last.get("ranked_files", [])))
        resolved = [f.strip() for f in raw.split(",") if f.strip()]

    if not resolved:
        click.echo("No files recorded.", err=True)
        sys.exit(1)

    record_resolved(last["bug_input"], resolved, last.get("signals", {}))

    click.echo(f"\n✓ Saved. These files will rank higher for similar errors next time:")
    for f in resolved:
        click.echo(f"  - {f}")


@cli.command()
def stats():
    """Print graph stats."""
    dug_dir = get_dug_dir()
    if not (dug_dir / "graph.json").exists():
        click.echo("No index found. Run: dug init", err=True)
        sys.exit(1)

    from .graph import CodeGraph
    from .vector_store import get_or_create_table
    cfg = load_config()
    graph = CodeGraph()
    graph.load(dug_dir / "graph.json")
    s = graph.stats()
    click.echo("\nGraph stats:")
    for kind, count in s["nodes"].items():
        click.echo(f"  {kind}: {count}")
    click.echo(f"  Edges: {s['edges']}")
    try:
        table = get_or_create_table(dug_dir / "embeddings", cfg.get("embedding_mode", "local"))
        click.echo(f"  Chunks (embedded): {table.count_rows()}")
    except Exception:
        click.echo("  Chunks (embedded): n/a")


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
