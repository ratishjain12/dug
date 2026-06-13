"""File watcher — OS-native filesystem events + 1.5s debounce before reindex."""

from __future__ import annotations

import threading
import time
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from .graph import LANG_EXTENSIONS, _should_ignore

DEBOUNCE_SECONDS = 1.5


class _DebounceHandler(FileSystemEventHandler):
    def __init__(self, root: Path, ignore_paths: list[str],
                 valid_exts: set[str], embedder):
        self.root = root
        self.ignore_paths = ignore_paths
        self.valid_exts = valid_exts
        self.embedder = embedder
        self._timers: dict[str, threading.Timer] = {}
        self._lock = threading.Lock()

    # watchdog fires on_modified for saves, on_created for new files,
    # on_deleted for deletions — all three need reindex
    def on_modified(self, event):
        self._handle(event)

    def on_created(self, event):
        self._handle(event)

    def on_deleted(self, event):
        self._handle(event)

    def _handle(self, event):
        if event.is_directory:
            return
        path = Path(event.src_path)
        if path.suffix not in self.valid_exts:
            return
        if _should_ignore(path, self.ignore_paths):
            return
        self._schedule(path)

    def _schedule(self, path: Path) -> None:
        """Debounce: reset the timer on every save, fire only after silence."""
        key = str(path)
        with self._lock:
            if key in self._timers:
                self._timers[key].cancel()
            timer = threading.Timer(DEBOUNCE_SECONDS, self._reindex, args=[path])
            self._timers[key] = timer
            timer.start()

    def _reindex(self, path: Path) -> None:
        from .indexer import update_file
        key = str(path)
        with self._lock:
            self._timers.pop(key, None)
        try:
            result = update_file(path, self.root, self.embedder)
            if not result.get("skipped"):
                rel = result.get("updated", path.name)
                chunks = result.get("chunks", 0)
                print(f"\r[dug] ✓ {rel}  ({chunks} chunks reindexed)        ", flush=True)
        except Exception as e:
            print(f"\r[dug] ✗ error reindexing {path.name}: {e}", flush=True)


def start_watch(root: Path | None = None) -> None:
    """Start the file watcher. Blocks until Ctrl+C."""
    from .config import load_config
    from .embeddings import get_embedder

    from .config import find_repo_root
    root = root or find_repo_root()
    config = load_config()

    valid_exts: set[str] = set()
    for lang in config.get("languages", []):
        valid_exts.update(LANG_EXTENSIONS.get(lang, []))

    embedder = get_embedder(config)
    handler = _DebounceHandler(root, config.get("ignore_paths", []), valid_exts, embedder)

    observer = Observer()
    observer.schedule(handler, str(root), recursive=True)
    observer.start()

    print(f"[dug] watching {root}")
    print(f"[dug] debounce: {DEBOUNCE_SECONDS}s — Ctrl+C to stop")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        observer.stop()
        observer.join()
        print("\n[dug] watcher stopped.")
