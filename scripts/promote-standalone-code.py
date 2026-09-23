#!/usr/bin/env python3
"""Promote whole-line inline code in existing OneNote Markdown without regenerating notes."""

import argparse
import os
import stat
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from onenote_to_markdown import promote_standalone_inline_code  # noqa: E402


def replace_atomically(path: Path, content: str) -> None:
    original_mode = stat.S_IMODE(path.stat().st_mode)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as temporary:
            temporary.write(content)
        os.chmod(temporary_name, original_mode)
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("roots", nargs="+", type=Path, help="existing Markdown directories to inspect")
    parser.add_argument("--write", action="store_true", help="apply the reported changes (default: dry run)")
    args = parser.parse_args()

    changes: list[tuple[Path, str]] = []
    summaries: list[tuple[Path, int, int]] = []
    for supplied_root in args.roots:
        root = supplied_root.resolve()
        if not root.is_dir():
            parser.error(f"not a directory: {root}")
        changed_files = 0
        promoted_lines = 0
        for path in sorted(root.rglob("*.md")):
            if path.is_symlink() or not path.is_file():
                continue
            with path.open("r", encoding="utf-8", newline="") as source:
                original = source.read()
            updated, count = promote_standalone_inline_code(original)
            if not count:
                continue
            changes.append((path, updated))
            changed_files += 1
            promoted_lines += count
        summaries.append((root, changed_files, promoted_lines))

    if args.write:
        for path, updated in changes:
            replace_atomically(path, updated)
    else:
        print("Dry run only; add --write to apply.")
    mode = "changed" if args.write else "would change"
    for root, changed_files, promoted_lines in summaries:
        print(f"{root}: {changed_files} files, {promoted_lines} lines {mode}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
