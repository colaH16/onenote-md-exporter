#!/usr/bin/env python3
"""Print OneNote canvas blocks and table cells for private curation work."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from onenote_to_markdown import Converter, MarkdownRenderer, node_literal_text  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect an archived OneNote page layout")
    parser.add_argument("page", type=Path, help="page archive directory or page.local.html")
    parser.add_argument("--tables", action="store_true", help="also list direct cells in each table")
    args = parser.parse_args()

    source = args.page
    if source.is_dir():
        source = source / "page.local.html"
    html = source.read_text(encoding="utf-8", errors="replace")
    renderer = MarkdownRenderer("assets")
    blocks = renderer.parse_blocks(html)
    for block in blocks:
        excerpt = " ".join(block.literal.split())[:160]
        print(f"block {block.key}: {excerpt}")
        if not args.tables:
            continue
        tables = ([block.node] if block.node.tag == "table" else []) + list(block.node.descendants("table"))
        for table_index, table in enumerate(tables):
            rows = Converter._table_rows(table)
            print(f"  table {table_index}: {len(rows)} rows")
            for row_index, row in enumerate(rows):
                for column_index, cell in enumerate(row):
                    cell_excerpt = " ".join(node_literal_text(cell).split())[:160]
                    print(f"    cell {row_index},{column_index}: {cell_excerpt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
