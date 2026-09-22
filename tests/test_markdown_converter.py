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
    current_page_name,
    is_onenote_internal_url,
    is_old_name,
    onenote_link_ids,
    silverbullet_relative_ref,
    tag_component,
    unlocalized_onenote_resource_ids,
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

    def test_heredoc_paragraphs_become_one_bash_block(self) -> None:
        source = """
        <html><body><div>
          <p># sudo tee -a /mnt/zfs/etc/dnf/dnf.conf &lt;&lt; 'EOF'</p>
          <br />
          <p>sudo tee -a /etc/dnf/dnf.conf &lt;&lt; 'EOF'</p>
          <p>installonly_limit=5</p>
          <p># 저장할 kernel 갯수</p>
          <p>EOF</p>
        </div></body></html>
        """
        renderer = MarkdownRenderer("Page.assets")
        markdown, _ = renderer.render_document(source)
        self.assertIn("```bash\n# sudo tee -a /mnt/zfs/etc/dnf/dnf.conf << 'EOF'", markdown)
        self.assertIn("\n# 저장할 kernel 갯수\nEOF\n```", markdown)
        self.assertNotIn("\n# 저장할 kernel 갯수\n\n", markdown)
        self.assertEqual(1, renderer.shell_code_blocks)

    def test_heredoc_object_marker_before_terminator_is_split(self) -> None:
        source = """
        <html><body><div>
          <p>tee /etc/sysctl.d/example.conf &lt;&lt; 'EOF'</p>
          <p>kernel.panic = 10</p>
          <p>kernel.panic_on_oops = 1￼EOF</p>
        </div></body></html>
        """
        markdown, _ = MarkdownRenderer("Page.assets").render_document(source)
        self.assertIn("kernel.panic_on_oops = 1\nEOF\n```", markdown)
        self.assertNotIn("￼", markdown)

    def test_single_command_is_inline_and_adjacent_commands_are_fenced(self) -> None:
        single, _ = MarkdownRenderer("Page.assets").render_document(
            "<html><body><div><p>sudo dnf install jq</p></div></body></html>"
        )
        self.assertEqual("`sudo dnf install jq`", single)

        renderer = MarkdownRenderer("Page.assets")
        multiple, _ = renderer.render_document(
            "<html><body><div><p>kubectl get pods</p><p>kubectl get svc</p></div></body></html>"
        )
        self.assertEqual("```bash\nkubectl get pods\nkubectl get svc\n```", multiple)
        self.assertEqual(1, renderer.shell_code_blocks)

    def test_backslash_continuation_becomes_one_bash_block(self) -> None:
        source = """
        <html><body><div>
          <p>sudo dnf remove docker \\</p>
          <p>docker-client \\</p>
          <p>docker-common</p>
        </div></body></html>
        """
        markdown, _ = MarkdownRenderer("Page.assets").render_document(source)
        self.assertEqual(
            "```bash\nsudo dnf remove docker \\\ndocker-client \\\ndocker-common\n```",
            markdown,
        )

    def test_bash_for_loop_becomes_one_code_block(self) -> None:
        source = """
        <html><body><div>
          <p>for port in 53 443</p><p>do</p>
          <p>firewall-cmd --add-port=$port/tcp</p><p>done</p>
        </div></body></html>
        """
        markdown, _ = MarkdownRenderer("Page.assets").render_document(source)
        self.assertEqual(
            "```bash\nfor port in 53 443\ndo\nfirewall-cmd --add-port=$port/tcp\ndone\n```",
            markdown,
        )

    def test_bare_root_prompt_command_is_not_a_markdown_heading(self) -> None:
        markdown, _ = MarkdownRenderer("Page.assets").render_document(
            "<html><body><div><p># journalctl</p></div></body></html>"
        )
        self.assertEqual("`# journalctl`", markdown)

    def test_external_command_url_can_be_code_but_onenote_page_link_stays_a_link(self) -> None:
        external, _ = MarkdownRenderer("Page.assets").render_document(
            '<html><body><div><p>sudo dnf install '
            '<a href="https://example.com/package.rpm">https://example.com/package.rpm</a>'
            '</p></div></body></html>'
        )
        self.assertEqual("`sudo dnf install https://example.com/package.rpm`", external)

        internal, _ = MarkdownRenderer("Page.assets").render_document(
            '<html><body><div><p><a href="onenote:#dnf%20update&amp;page-id='
            '%7B22222222-2222-2222-2222-222222222222%7D">dnf update</a></p></div></body></html>'
        )
        self.assertIn("[dnf update](onenote:", internal)
        self.assertNotIn("`dnf update`", internal)

        adjacent, _ = MarkdownRenderer("Page.assets").render_document(
            '<html><body><div><p>sudo dnf update</p><p><a href="onenote:#dnf%20update&amp;page-id='
            '%7B22222222-2222-2222-2222-222222222222%7D">dnf update</a></p></div></body></html>'
        )
        self.assertIn("`sudo dnf update`", adjacent)
        self.assertIn("[dnf update](onenote:", adjacent)

    def test_explicit_fish_commands_use_fish_fence(self) -> None:
        renderer = MarkdownRenderer("Page.assets")
        markdown, _ = renderer.render_document(
            "<html><body><div><p>set -gx EDITOR nvim</p><p>set -gx PAGER less</p></div></body></html>"
        )
        self.assertEqual("```fish\nset -gx EDITOR nvim\nset -gx PAGER less\n```", markdown)

    def test_multi_cell_table_preserves_plain_cell_content(self) -> None:
        source = """
        <html><body><div><table><tr>
          <td><p>sudo dnf install jq</p></td><td><p>설명</p></td>
        </tr></table></div></body></html>
        """
        renderer = MarkdownRenderer("Page.assets")
        markdown, _ = renderer.render_document(source)
        self.assertIn("| sudo dnf install jq | 설명 |", markdown)
        self.assertNotIn("`sudo dnf install jq`", markdown)
        self.assertEqual(0, renderer.inline_shell_commands)

    def test_command_with_explanation_becomes_text_code_block(self) -> None:
        renderer = MarkdownRenderer("Page.assets")
        markdown, _ = renderer.render_document(
            "<html><body><div><p>firewall-cmd --list-all 명령으로 masquerade yes 확인</p>"
            "</div></body></html>"
        )
        self.assertEqual(
            "```text\nfirewall-cmd --list-all 명령으로 masquerade yes 확인\n```",
            markdown,
        )
        self.assertEqual(1, renderer.shell_code_blocks)
        self.assertEqual([], renderer.shell_reviews)

    def test_mixed_command_object_markers_become_code_block_line_breaks(self) -> None:
        renderer = MarkdownRenderer("Page.assets")
        markdown, _ = renderer.render_document(
            "<html><body><div><p>pveceph osd create &lt;dev&gt; [OPTIONS]￼￼Create OSD￼"
            "--db_dev &lt;string&gt;￼Block device name for block.db.</p></div></body></html>"
        )
        self.assertIn(
            "```text\npveceph osd create <dev> [OPTIONS]\nCreate OSD\n--db_dev <string>\n"
            "Block device name for block.db.\n```",
            markdown,
        )
        self.assertNotIn("￼", markdown)
        self.assertEqual([], renderer.shell_reviews)

    def test_file_uri_is_not_treated_as_a_relative_asset(self) -> None:
        renderer = MarkdownRenderer("Page.assets")
        self.assertTrue(renderer.rewrite_url(r"file:///\\server\share").startswith("file:///"))

    def test_side_block_creates_stable_review_record_and_anchor(self) -> None:
        source = """
        <html><body>
          <div style="position:absolute;top:100px;left:100px;width:300px"><p>Main concept</p></div>
          <div style="position:absolute;top:120px;left:420px;width:180px"><p>Side explanation</p></div>
        </body></html>
        """
        renderer = MarkdownRenderer("Page.assets", review_id_prefix="example")
        markdown, count = renderer.render_document(source)
        self.assertEqual(1, count)
        self.assertEqual(1, len(renderer.layout_reviews))
        self.assertEqual("example-01", renderer.layout_reviews[0]["reviewId"])
        self.assertIn('<a id="layout-review-example-01"></a>', markdown)
        self.assertEqual(
            "Main concept",
            renderer.layout_reviews[0]["candidateTarget"]["markdown"],
        )
        self.assertEqual(
            "Side explanation",
            renderer.layout_reviews[0]["annotation"]["markdown"],
        )

    def test_unlocalized_onenote_resource_url_is_detected(self) -> None:
        source = (
            '<img src="https://graph.microsoft.com/v1.0/users(\'person@example.com\')/onenote/'
            'resources/resource-id/$value" />'
        )
        self.assertEqual({"resource-id"}, unlocalized_onenote_resource_ids(source))

    def test_classic_onenote_link_ids_survive_html_section_entity_conversion(self) -> None:
        link = (
            "onenote:#Target%C2%A7ion-id=%7B11111111-1111-1111-1111-111111111111%7D"
            "&page-id=%7B22222222-2222-2222-2222-222222222222%7D&end"
        )
        self.assertTrue(is_onenote_internal_url(link))
        self.assertEqual(
            (
                "11111111-1111-1111-1111-111111111111",
                "22222222-2222-2222-2222-222222222222",
            ),
            onenote_link_ids(link),
        )
        self.assertEqual("../Other/Target", silverbullet_relative_ref(
            Path("Book/Section/Source.md"), Path("Book/Other/Target.md")
        ))


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

    def test_extension_like_page_title_is_made_safe_for_silverbullet(self) -> None:
        self.assertEqual("dnf-conf", current_page_name("dnf.conf"))
        self.assertEqual("0526 5-2", current_page_name("0526 5.2"))
        self.assertEqual("ordinary page", current_page_name("ordinary page"))

    def test_tag_component_is_stable_and_picker_friendly(self) -> None:
        self.assertEqual("대학-노트-3-1", tag_component("대학 노트 3 - 1"))


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
            review_report = json.loads((project / "output/markdown/_meta/layout-review.json").read_text())
            self.assertEqual(0, review_report["count"])
            self.assertTrue((project / "output/markdown/_meta/layout-review.md").is_file())
            markdown = (project / "output/markdown/Notebook/Section/Page.md").read_text()
            self.assertIn('archive_status: "complete"', markdown)
            self.assertIn('source_archive_status: "incomplete"', markdown)
            self.assertIn("tags: source/onenote type/note", markdown)
            self.assertIn("has/document", markdown)
            self.assertIn("document/video", markdown)
            self.assertIn("document_count: 1", markdown)
            self.assertIn('document_types: "mov"', markdown)
            self.assertNotIn("OneNote 아카이브 일부 누락", markdown)

            notebook_index = (project / "output/markdown/Notebook/_index.md").read_text(encoding="utf-8")
            self.assertIn("tags: meta/onenote/index source/onenote", notebook_index)
            document_guide = (project / "output/markdown/_meta/document-picker.md").read_text(encoding="utf-8")
            self.assertIn("tags: meta/onenote/documents", document_guide)
            self.assertIn("| `mov` | 1 |", document_guide)
            tag_guide = (project / "output/markdown/_meta/tag-guide.md").read_text(encoding="utf-8")
            self.assertIn("tags: meta/onenote/tags", tag_guide)
            self.assertIn("| `#document/video` | 1 |", tag_guide)

            (page / "page.local.html").write_text(
                '<html><body><img src="https://graph.microsoft.com/v1.0/me/onenote/'
                'resources/missed-image/$value" /></body></html>',
                encoding="utf-8",
            )
            Converter(project, config, replace=True).convert()
            second_report = json.loads(
                (project / "output/markdown/_meta/conversion-report.json").read_text()
            )
            self.assertEqual(1, second_report["stats"]["incompleteArchivePages"])
            self.assertEqual(1, second_report["stats"]["unlocalizedResourcePages"])
            self.assertEqual(1, second_report["stats"]["unlocalizedResources"])
            second_markdown = (project / "output/markdown/Notebook/Section/Page.md").read_text()
            self.assertIn('archive_status: "incomplete"', second_markdown)
            self.assertIn("OneNote 원격 리소스 URL 1개", second_markdown)


class InternalLinkTests(unittest.TestCase):
    def test_page_section_and_override_links_become_silverbullet_page_links(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            config_dir = project / ".local-config"
            staging = project / "output/markdown-staging"
            source = staging / "Book/Section/Source.md"
            target = staging / "Book/Section/Target.md"
            section_index = staging / "Book/Other/_index.md"
            moved = staging / "Book/Other/Moved.md"
            for path in (source, target, section_index, moved):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("# test\n", encoding="utf-8")

            page_id = "22222222-2222-2222-2222-222222222222"
            page_section_id = "11111111-1111-1111-1111-111111111111"
            other_section_id = "33333333-3333-3333-3333-333333333333"
            moved_page_id = "44444444-4444-4444-4444-444444444444"
            source.write_text(
                "\n".join([
                    f"[Target](onenote:#Target&section-id={{{page_section_id}}}&page-id={{{page_id}}}&end)",
                    f"[Trailing \\](onenote:#Target&section-id={{{page_section_id}}}&page-id={{{page_id}}}&end)",
                    f"[Other section](onenote:#Other&section-id={{{other_section_id}}}&end)",
                    f"[Moved](onenote:#Moved&section-id={{{other_section_id}}}&page-id={{{moved_page_id}}}&end)",
                ]) + "\n",
                encoding="utf-8",
            )
            config_dir.mkdir()
            config = config_dir / "markdown.json"
            config.write_text(json.dumps({
                "sourceArchiveRoot": "./output/archive",
                "outputRoot": "./output/markdown",
                "silverBulletRoot": "OneNote/markdown",
                "notebooks": [{"id": "allowed-id", "name": "Book"}],
                "internalLinkOverrides": {moved_page_id: "Book/Other/Moved.md"},
            }), encoding="utf-8")
            converter = Converter(project, config)
            converter.mapping = [
                {
                    "markdown": "Book/Section/Target.md",
                    "sectionMarkdown": "Book/Section/_index.md",
                    "legacySectionId": page_section_id,
                    "legacyPageId": page_id,
                },
                {
                    "markdown": "Book/Other/Moved.md",
                    "sectionMarkdown": "Book/Other/_index.md",
                    "legacySectionId": other_section_id,
                    "legacyPageId": "55555555-5555-5555-5555-555555555555",
                },
            ]
            converter.rewrite_internal_links(staging)
            markdown = source.read_text(encoding="utf-8")
            self.assertIn("[Target](</OneNote/markdown/Book/Section/Target>)", markdown)
            self.assertIn("[Trailing \\\\](</OneNote/markdown/Book/Section/Target>)", markdown)
            self.assertIn("[Other section](</OneNote/markdown/Book/Other/_index>)", markdown)
            self.assertIn("[Moved](</OneNote/markdown/Book/Other/Moved>)", markdown)
            self.assertNotIn("onenote:", markdown)
            self.assertEqual(4, converter.stats["internalLinksFound"])
            self.assertEqual(4, converter.stats["internalLinksRewritten"])
            self.assertEqual(1, converter.stats["internalLinkOverrides"])


class CurationTests(unittest.TestCase):
    def make_project(self, temporary: str, curation: dict) -> tuple[Path, Path]:
        project = Path(temporary)
        notebook = project / "output/archive/Notebook"
        section = notebook / "Section"
        page = section / "page-id"
        page.mkdir(parents=True)
        (notebook / "notebook.json").write_text(
            json.dumps({"id": "allowed-id", "displayName": "Notebook"}), encoding="utf-8"
        )
        (section / "section.json").write_text(
            json.dumps({"id": "section-id", "displayName": "Section"}), encoding="utf-8"
        )
        (page / "page.local.html").write_text(
            """<html><body>
            <div style="position:absolute;top:100px;left:50px;width:300px"><p>Main procedure</p></div>
            <div style="position:absolute;top:100px;left:700px;width:300px"><p>Old attempt</p></div>
            </body></html>""",
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
                "archiveStatus": "complete",
                "needsVisualReview": True,
                "resources": [],
            }),
            encoding="utf-8",
        )
        config_dir = project / ".local-config"
        config_dir.mkdir()
        curation_path = config_dir / "curation.json"
        curation_path.write_text(
            json.dumps({"schemaVersion": 1, "pages": {"page-id": curation}}), encoding="utf-8"
        )
        config = config_dir / "markdown.json"
        config.write_text(
            json.dumps({
                "sourceArchiveRoot": "./output/archive",
                "outputRoot": "./output/markdown",
                "curationFile": "./.local-config/curation.json",
                "notebooks": [{"id": "allowed-id", "name": "Notebook"}],
            }),
            encoding="utf-8",
        )
        return project, config

    def test_curation_reorders_blocks_and_resolves_visual_review(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, config = self.make_project(temporary, {
                "resolved": True,
                "layout": [
                    {"type": "block", "block": "100,700", "heading": "## Reference"},
                    {"type": "block", "block": "100,50", "heading": "## Procedure"},
                ],
            })
            Converter(project, config).convert()
            markdown = (project / "output/markdown/Notebook/Section/Page.md").read_text(encoding="utf-8")
            self.assertLess(markdown.index("Old attempt"), markdown.index("Main procedure"))
            self.assertIn("needs_visual_review: false", markdown)
            self.assertIn("layout_curated: true", markdown)
            review = json.loads(
                (project / "output/markdown/_meta/layout-review.json").read_text(encoding="utf-8")
            )
            self.assertEqual(0, review["count"])

    def test_curation_rejects_unaccounted_source_block(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, config = self.make_project(temporary, {
                "resolved": True,
                "layout": [{"type": "block", "block": "100,50"}],
            })
            with self.assertRaisesRegex(RuntimeError, "unaccounted"):
                Converter(project, config).convert()


if __name__ == "__main__":
    unittest.main()
