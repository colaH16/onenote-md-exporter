#!/usr/bin/env python3

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from onenote_to_markdown import (  # noqa: E402
    Converter,
    MarkdownRenderer,
    build_page_tree,
    current_name,
    is_old_name,
)


class MarkdownRendererTests(unittest.TestCase):
    def test_long_ocr_image_alt_falls_back_to_file_name(self) -> None:
        long_alt = "OCR text " * 40
        source = f'<html><body><div><img src="assets/example image.png" alt="{long_alt}" /></div></body></html>'
        markdown, _ = MarkdownRenderer("Page.assets").render_document(source)
        self.assertIn("![example image](Page.assets/example%20image.png)", markdown)
        self.assertNotIn("OCR text OCR text", markdown)

    def test_single_cell_table_becomes_code_block(self) -> None:
        source = """
        <html><body><div><table><tr><td>
          <p>arbitrary text</p><p>  indented text that is not a shell command</p>
        </td></tr></table></div></body></html>
        """
        markdown, _ = MarkdownRenderer("Page.assets").render_document(source)
        self.assertIn("```\narbitrary text\n  indented text that is not a shell command", markdown)
        self.assertNotIn("\n ```", markdown)
        self.assertNotIn("| --- |", markdown)

    def test_file_uri_is_not_treated_as_a_relative_asset(self) -> None:
        renderer = MarkdownRenderer("Page.assets")
        self.assertTrue(renderer.rewrite_url(r"file:///\\server\share").startswith("file:///"))


class HierarchyTests(unittest.TestCase):
    def test_page_levels_form_parent_child_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            section = Path(temporary)
            samples = [
                ("parent", "Parent", 0, 0),
                ("child", "Child", 1, 1),
                ("root", "Root", 0, 2),
            ]
            for directory, title, level, order in samples:
                page_dir = section / directory
                page_dir.mkdir()
                (page_dir / "page.json").write_text(
                    json.dumps({"id": directory, "title": title, "level": level, "order": order}),
                    encoding="utf-8",
                )
            roots = build_page_tree(section, [])
            self.assertEqual(["Parent", "Root"], [page.title for page in roots])
            self.assertEqual(["Child"], [page.title for page in roots[0].children])

    def test_old_prefix_is_removed_but_status_is_detectable(self) -> None:
        self.assertTrue(is_old_name("---deprecated"))
        self.assertEqual("deprecated", current_name("---deprecated"))


class AllowlistTests(unittest.TestCase):
    def test_only_allowlisted_notebook_is_discovered(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            archive = project / "output/archive"
            archive.mkdir(parents=True)
            for notebook_id, directory in (("allowed-id", "Allowed"), ("private-id", "Private")):
                notebook = archive / directory
                notebook.mkdir()
                (notebook / "notebook.json").write_text(
                    json.dumps({"id": notebook_id, "displayName": directory}), encoding="utf-8"
                )
            config_dir = project / ".local-config"
            config_dir.mkdir()
            config = config_dir / "markdown.json"
            config.write_text(
                json.dumps({
                    "sourceArchiveRoot": "./output/archive",
                    "outputRoot": "./output/markdown",
                    "notebooks": [{"id": "allowed-id", "name": "Allowed"}],
                }),
                encoding="utf-8",
            )
            converter = Converter(project, config)
            discovered = converter.discover_notebooks()
            self.assertEqual(1, len(discovered))
            self.assertEqual("allowed-id", discovered[0][1]["id"])

    def test_manually_supplied_failed_resource_is_reconciled(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            notebook = project / "output/archive/Notebook"
            section = notebook / "Section"
            page = section / "page-id"
            assets = page / "assets"
            assets.mkdir(parents=True)
            (notebook / "notebook.json").write_text(
                json.dumps({"id": "allowed-id", "displayName": "Notebook"}), encoding="utf-8"
            )
            (section / "section.json").write_text(
                json.dumps({"id": "section-id", "displayName": "Section"}), encoding="utf-8"
            )
            (page / "page.local.html").write_text(
                '<html><body><div><object data="assets/video.mov" data-attachment="video.mov"></object></div></body></html>',
                encoding="utf-8",
            )
            (page / "page.raw.html").write_text("<html></html>", encoding="utf-8")
            (page / "layout.json").write_text("{}", encoding="utf-8")
            (page / "page.json").write_text(
                json.dumps({
                    "id": "page-id",
                    "title": "Page",
                    "level": 0,
                    "order": 0,
                    "archiveStatus": "incomplete",
                    "resources": [{"fileName": "video.mov", "status": "failed"}],
                }),
                encoding="utf-8",
            )
            (assets / "video.mov").write_bytes(b"manually supplied")
            config_dir = project / ".local-config"
            config_dir.mkdir()
            config = config_dir / "markdown.json"
            config.write_text(
                json.dumps({
                    "sourceArchiveRoot": "./output/archive",
                    "outputRoot": "./output/markdown",
                    "notebooks": [{"id": "allowed-id", "name": "Notebook"}],
                }),
                encoding="utf-8",
            )
            converter = Converter(project, config)
            converter.convert()
            report = json.loads((project / "output/markdown/_meta/conversion-report.json").read_text())
            self.assertEqual(0, report["stats"]["incompleteArchivePages"])
            self.assertEqual(1, report["stats"]["reconciledArchivePages"])
            markdown = (project / "output/markdown/Notebook/Section/Page.md").read_text()
            self.assertIn('archive_status: "complete"', markdown)
            self.assertIn('source_archive_status: "incomplete"', markdown)
            self.assertNotIn("OneNote 아카이브 일부 누락", markdown)


if __name__ == "__main__":
    unittest.main()
