#!/usr/bin/env python3
"""Convert the preserved OneNote HTML archive into SilverBullet Markdown.

The converter deliberately uses only Python's standard library. The private
allowlist in .local-config/markdown.json is the authority: archive notebooks
that are not listed there are never traversed or copied.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import html
import json
import os
import re
import shutil
import sys
import tempfile
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable, Iterator


VOID_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}
BLOCK_TAGS = {
    "address",
    "article",
    "aside",
    "blockquote",
    "div",
    "dl",
    "fieldset",
    "figure",
    "footer",
    "form",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "hr",
    "main",
    "nav",
    "ol",
    "p",
    "pre",
    "section",
    "table",
    "ul",
}
SKIP_TAGS = {"head", "script", "style", "svg"}
MONOSPACE_FONTS = ("consolas", "courier", "menlo", "monaco", "monospace", "d2coding")
INVALID_PATH_CHARS = re.compile(r'[\x00-\x1f<>:"/\\|?*]')
ARCHIVE_ID_SUFFIX = re.compile(r"--[0-9a-f]{8}$", re.IGNORECASE)
OLD_PREFIX = re.compile(r"^--+")
PAGE_NAME_EXTENSION = re.compile(r"\.([A-Za-z0-9]+)$")
ONENOTE_RESOURCE_URL = re.compile(
    r'https://graph\.microsoft\.com/[^"\s<>]*/onenote/resources/([^/?#"\s<>]+)/\$value',
    re.IGNORECASE,
)
MARKDOWN_LINK = re.compile(r"(?<!!)\[(?P<label>[^\]]*)\]\((?P<url>[^)\n]+)\)")
LEGACY_ONENOTE_ID = r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"
IMAGE_EXTENSIONS = {"avif", "bmp", "gif", "heic", "heif", "jpeg", "jpg", "png", "svg", "tif", "tiff", "webp"}
VIDEO_EXTENSIONS = {"avi", "m4v", "mkv", "mov", "mp4", "mpeg", "mpg", "webm"}
AUDIO_EXTENSIONS = {"aac", "flac", "m4a", "mp3", "ogg", "opus", "wav", "wma"}
HEREDOC_START = re.compile(
    r"^(?:#\s*)?(?:sudo\s+)?(?:cat|tee)\b.*?<<-?\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?\s*$",
    re.IGNORECASE,
)
SHELL_COMMANDS_WITH_SUBCOMMANDS: dict[str, set[str]] = {
    "apt": {"autoclean", "autoremove", "clean", "download", "full-upgrade", "install", "list", "purge", "remove", "search", "show", "update", "upgrade"},
    "apt-get": {"autoclean", "autoremove", "clean", "download", "install", "purge", "remove", "update", "upgrade"},
    "dnf": {"check-update", "clean", "config-manager", "download", "group", "groupinstall", "info", "install", "list", "makecache", "provides", "reinstall", "remove", "repoquery", "search", "update", "upgrade", "whatprovides"},
    "yum": {"check-update", "clean", "config-manager", "group", "groupinstall", "info", "install", "list", "localinstall", "makecache", "provides", "reinstall", "remove", "search", "update", "upgrade", "whatprovides"},
    "zypper": {"addrepo", "ar", "clean", "dist-upgrade", "download", "dup", "in", "info", "install", "list-updates", "lr", "modifyrepo", "mr", "patch", "ref", "refresh", "remove", "repos", "rm", "se", "search", "up", "update"},
    "systemctl": {"cat", "daemon-reexec", "daemon-reload", "disable", "edit", "enable", "is-active", "is-enabled", "list-timers", "mask", "reload", "restart", "show", "start", "status", "stop", "unmask"},
    "kubectl": {"annotate", "api-resources", "apply", "auth", "autoscale", "cluster-info", "config", "cordon", "cp", "create", "delete", "describe", "diff", "drain", "edit", "exec", "explain", "get", "label", "logs", "patch", "port-forward", "replace", "rollout", "run", "scale", "taint", "top", "uncordon", "wait"},
    "helm": {"create", "dependency", "get", "history", "install", "lint", "list", "package", "plugin", "pull", "repo", "rollback", "search", "show", "status", "template", "test", "uninstall", "upgrade", "verify", "version"},
    "docker": {"attach", "build", "commit", "compose", "container", "cp", "create", "exec", "image", "images", "info", "inspect", "kill", "load", "login", "logout", "logs", "network", "node", "pause", "port", "ps", "pull", "push", "restart", "rm", "rmi", "run", "save", "service", "stack", "start", "stats", "stop", "swarm", "system", "tag", "top", "unpause", "update", "version", "volume"},
    "podman": {"build", "commit", "compose", "container", "cp", "create", "exec", "generate", "image", "images", "info", "inspect", "kill", "load", "login", "logs", "network", "pause", "pod", "port", "ps", "pull", "push", "restart", "rm", "rmi", "run", "save", "start", "stats", "stop", "system", "tag", "top", "unpause", "version", "volume"},
    "git": {"add", "branch", "checkout", "cherry-pick", "clean", "clone", "commit", "config", "diff", "fetch", "init", "log", "merge", "mv", "pull", "push", "rebase", "remote", "reset", "restore", "revert", "show", "stash", "status", "switch", "tag"},
    "ip": {"addr", "address", "link", "neigh", "netns", "route", "rule", "tunnel"},
}
SHELL_COMMANDS_WITH_ARGUMENTS = {
    "abbr", "alias", "awk", "base64", "blkid", "btrfs", "buildah", "cat", "cd", "ceph",
    "cephadm", "chattr", "chmod", "chown", "chroot", "chsh", "cp", "crictl", "ctr", "curl",
    "cut", "date", "dd", "df", "dkms", "dracut", "du", "echo", "efibootmgr", "export",
    "exportfs", "fdisk", "find", "firewall-cmd", "fish_add_path", "free", "fuser", "gluster",
    "grep", "grub2-mkconfig", "grub-mkconfig", "grubby", "head", "hostnamectl", "ip6tables",
    "iptables", "journalctl", "jq", "k3s", "kill", "killall", "ln", "loginctl", "losetup", "ls",
    "lsblk", "lsmod", "lvs", "lvcreate", "lvdisplay", "lvextend", "lvreduce", "make", "mdadm",
    "mkdir", "mkfs", "mkfs.btrfs", "mkfs.ext4", "mkfs.xfs", "mkinitrd", "modprobe", "mount",
    "mv", "nano", "nerdctl", "netstat", "nft", "nmcli", "oc", "openssl", "parted", "podman",
    "printf", "ps", "pv", "pvcreate", "pvdisplay", "pveceph", "rbd", "rke2", "rm", "rpm",
    "rsync", "sed", "skopeo", "smartctl", "smbpasswd", "snapper", "sort", "ss", "ssh", "swapon",
    "swapoff", "sysctl", "systemd-firstboot", "tail", "tar", "tee", "timedatectl", "touch", "tr",
    "udevadm", "umount", "update-alternatives", "update-bootloader", "update-grub", "vgcreate",
    "vgdisplay", "vi", "vim", "virsh", "watch", "wget", "wipefs", "xargs", "yq", "zfs", "zpool",
}
SHELL_PROSE_MARKERS = (" 또는 ", " -> ", " = ", " 하면 ", " 위해 ", " 확인 ", " 변경 ")


@dataclass
class HtmlNode:
    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    children: list[HtmlNode | str] = field(default_factory=list)
    parent: HtmlNode | None = None

    def child_nodes(self, tag: str | None = None) -> Iterator[HtmlNode]:
        for child in self.children:
            if isinstance(child, HtmlNode) and (tag is None or child.tag == tag):
                yield child

    def descendants(self, tag: str | None = None) -> Iterator[HtmlNode]:
        for child in self.child_nodes():
            if tag is None or child.tag == tag:
                yield child
            yield from child.descendants(tag)


@dataclass
class RenderedBlock:
    """A top-level OneNote canvas block before layout interpretation."""

    key: str
    node: HtmlNode
    markdown: str
    literal: str
    position: tuple[float, float, float | None] | None


class OneNoteHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = HtmlNode("document")
        self.stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        node = HtmlNode(tag, {key.lower(): value or "" for key, value in attrs}, parent=self.stack[-1])
        self.stack[-1].children.append(node)
        if tag not in VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() not in VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return

    def handle_data(self, data: str) -> None:
        self.stack[-1].children.append(data)


def parse_style(value: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for declaration in value.split(";"):
        if ":" not in declaration:
            continue
        key, item = declaration.split(":", 1)
        result[key.strip().lower()] = item.strip()
    return result


def numeric_css(value: str | None) -> float | None:
    if not value:
        return None
    match = re.search(r"-?[0-9]+(?:\.[0-9]+)?", value)
    return float(match.group(0)) if match else None


def collapse_inline_space(value: str) -> str:
    return re.sub(r"\s+", " ", value)


def normalize_markdown(value: str) -> str:
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = re.sub(r"[ \t]+\n", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    value = re.sub(r"\*\*\s*\*\*", "", value)
    return value.strip()


def node_text(node: HtmlNode) -> str:
    parts: list[str] = []
    for child in node.children:
        if isinstance(child, str):
            parts.append(child)
        elif child.tag == "br":
            parts.append("\n")
        elif child.tag not in SKIP_TAGS:
            parts.append(node_text(child))
    return collapse_inline_space("".join(parts)).strip()


def node_literal_text(node: HtmlNode) -> str:
    parts: list[str] = []
    for child in node.children:
        if isinstance(child, str):
            parts.append(child.replace("\u00a0", " "))
        elif child.tag == "br":
            parts.append("\n")
        elif child.tag not in SKIP_TAGS:
            parts.append(node_literal_text(child))
    value = "".join(parts).replace("\r\n", "\n").replace("\r", "\n")
    value = re.sub(r"\n[\t ]+\n", "\n\n", value)
    return value.rstrip()


def quote_yaml(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)


def front_matter(items: Iterable[tuple[str, object]]) -> str:
    lines = ["---"]
    for key, value in items:
        if key == "tags" and isinstance(value, str) and re.fullmatch(r"[^\s:]+(?:\s+[^\s:]+)*", value):
            lines.append(f"{key}: {value}")
        else:
            lines.append(f"{key}: {quote_yaml(value)}")
    lines.extend(["---", ""])
    return "\n".join(lines)


def safe_name(value: str, fallback: str = "untitled", maximum: int = 120) -> str:
    value = INVALID_PATH_CHARS.sub("-", value)
    value = re.sub(r"\s+", " ", value).strip().rstrip(".")
    if value in {"", ".", ".."}:
        value = fallback
    if len(value) > maximum:
        value = value[:maximum].rstrip(" .")
    return value or fallback


def tag_component(value: str, fallback: str = "untitled") -> str:
    value = OLD_PREFIX.sub("", value.strip())
    value = re.sub(r"[^\w.-]+", "-", value, flags=re.UNICODE).strip("-_.").lower()
    value = re.sub(r"-{2,}", "-", value)
    return value or fallback


def is_old_name(value: str) -> bool:
    return bool(OLD_PREFIX.match(value.strip()))


def current_name(value: str, fallback: str = "untitled") -> str:
    stripped = OLD_PREFIX.sub("", value.strip()).strip(" -")
    return safe_name(stripped, fallback=fallback)


def current_page_name(value: str, fallback: str = "untitled") -> str:
    """Avoid leaf page names that SilverBullet interprets as documents by extension."""
    name = current_name(value, fallback=fallback)
    return PAGE_NAME_EXTENSION.sub(r"-\1", name)


def archive_display_name(value: str) -> str:
    return ARCHIVE_ID_SUFFIX.sub("", value)


def stable_short(value: str, length: int = 8) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def markdown_uri(path: str) -> str:
    return urllib.parse.quote(path.replace(os.sep, "/"), safe="/._-~")


def review_excerpt(value: str, maximum: int = 1200) -> str:
    """Keep review reports readable without losing the nearby Markdown shape."""
    value = normalize_markdown(value)
    if len(value) <= maximum:
        return value
    return value[:maximum].rstrip() + "\n…"


def unlocalized_onenote_resource_ids(value: str) -> set[str]:
    return {urllib.parse.unquote(match.group(1)) for match in ONENOTE_RESOURCE_URL.finditer(value)}


def normalize_legacy_onenote_id(value: str) -> str:
    return value.strip().strip("{}").lower()


def onenote_link_ids(value: str) -> tuple[str | None, str | None]:
    """Return the classic section/page GUIDs embedded in a OneNote link."""
    decoded = urllib.parse.unquote(value).replace("§ion-id=", "section-id=")
    section_match = re.search(rf"section-id=\{{?{LEGACY_ONENOTE_ID}\}}?", decoded, re.IGNORECASE)
    page_match = re.search(rf"page-id=\{{?{LEGACY_ONENOTE_ID}\}}?", decoded, re.IGNORECASE)
    if not page_match:
        web_target = re.search(
            rf"wd=target\([^|]*\|{LEGACY_ONENOTE_ID}/[^|]*\|{LEGACY_ONENOTE_ID}/",
            decoded,
            re.IGNORECASE,
        )
        if web_target:
            if not section_match:
                section_match = web_target
            page_id = normalize_legacy_onenote_id(web_target.group(2))
            section_id = normalize_legacy_onenote_id(web_target.group(1))
            return section_id, page_id
    section_id = normalize_legacy_onenote_id(section_match.group(1)) if section_match else None
    page_id = normalize_legacy_onenote_id(page_match.group(1)) if page_match else None
    return section_id, page_id


def is_onenote_internal_url(value: str) -> bool:
    decoded = urllib.parse.unquote(value).lower()
    return "onenote:" in decoded or ("onedrive.live.com" in decoded and "wd=target" in decoded)


def silverbullet_relative_ref(source: Path, target: Path) -> str:
    """Build a SilverBullet page ref, relative to source and without .md."""
    target_page = target.with_suffix("") if target.suffix.lower() == ".md" else target
    relative = os.path.relpath(target_page, source.parent).replace(os.sep, "/")
    return relative


def silverbullet_page_ref(source: Path, target: Path, space_root: str = "") -> str:
    """Build a page ref relative to a page, or absolute inside a configured SilverBullet root."""
    target_page = target.with_suffix("") if target.suffix.lower() == ".md" else target
    if space_root:
        return "/" + "/".join((space_root.strip("/"), target_page.as_posix().lstrip("/")))
    return silverbullet_relative_ref(source, target_page)


def fenced_code(value: str, language: str = "text") -> str:
    longest = max((len(match.group(0)) for match in re.finditer(r"`+", value)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}{language}\n{value or '(빈 블록)'}\n{fence}"


def fenced_text(value: str) -> str:
    return fenced_code(value, "text")


def inline_code(value: str) -> str:
    value = value.strip()
    longest = max((len(match.group(0)) for match in re.finditer(r"`+", value)), default=0)
    fence = "`" * max(1, longest + 1)
    padding = " " if "`" in value else ""
    return f"{fence}{padding}{value}{padding}{fence}"


def shell_prompt_body(value: str) -> str:
    return re.sub(r"^(?:(?:\$|#)\s+|#(?=sudo\b))", "", value.strip(), count=1)


def obvious_shell_command(value: str) -> bool:
    """Recognize command-only lines while rejecting headings and explanatory prose."""
    if "\uFFFC" in value:
        return False
    had_prompt = bool(re.match(r"^(?:(?:\$|#)\s+|#(?=sudo\b))", value.strip()))
    line = shell_prompt_body(value)
    if not line or line.startswith("#"):
        return False
    if line.startswith("#!"):
        return True
    if re.match(r"^echo\s+(['\"]).*\1(?:\s+#.*)?$", line) and not line.rstrip().endswith(";"):
        return True
    command_part = re.split(r"\s+#", line, maxsplit=1)[0]
    if any(marker in f" {command_part} " for marker in SHELL_PROSE_MARKERS):
        return False
    if re.match(r"^sudo\s+\S+", command_part):
        return True
    if re.match(r"^(?:export\s+)?[A-Za-z_][A-Za-z0-9_]*=(?:['\"/$~]|[^\s]+$)", command_part):
        return True
    if re.match(r"^set\s+-[A-Za-z]+(?:\s+\S+)+", command_part):
        return True
    match = re.match(r"^([A-Za-z][A-Za-z0-9_.+-]*)(?:\s+([^\s]+))?(?:\s+.*)?$", command_part)
    if not match:
        return False
    command = match.group(1).lower()
    argument = (match.group(2) or "").lower()
    if command in SHELL_COMMANDS_WITH_SUBCOMMANDS:
        recognized = argument in SHELL_COMMANDS_WITH_SUBCOMMANDS[command] or argument.startswith("-")
        syntactic = bool(re.search(r"(?:^|\s)--?\w|[/~$|<>]", command_part))
        return recognized and (had_prompt or syntactic or len(command_part.split()) >= 3)
    if command not in SHELL_COMMANDS_WITH_ARGUMENTS:
        return False
    if not argument:
        return had_prompt
    if command == "echo" and not had_prompt and command_part.rstrip().endswith(";"):
        return False
    # File-oriented commands without flags need a path, extension, expansion, or extra argument.
    return bool(
        argument.startswith("-")
        or re.search(r"[/.$~*?=:]", argument)
        or len(command_part.split()) >= 3
    )


def shell_language(values: Iterable[str]) -> str:
    combined = "\n".join(shell_prompt_body(value) for value in values)
    if re.search(
        r"(?m)^\s*(?:set\s+-[A-Za-z]+|function\s+|for\s+\S+\s+in\s+|while\s+|end\s*$|fish_add_path\s+|abbr\s+)",
        combined,
    ):
        return "fish"
    return "bash"


class MarkdownRenderer:
    def __init__(self, asset_prefix: str, review_id_prefix: str = "page") -> None:
        self.asset_prefix = asset_prefix.rstrip("/")
        self.review_id_prefix = review_id_prefix
        self.layout_reviews: list[dict[str, object]] = []
        self.shell_reviews: list[dict[str, str]] = []
        self.shell_code_blocks = 0
        self.inline_shell_commands = 0
        self._table_depth = 0
        self._shell_review_keys: set[tuple[str, str]] = set()

    def rewrite_url(self, value: str) -> str:
        value = html.unescape(value.strip())
        if value.startswith("assets/"):
            value = f"{self.asset_prefix}/{value.removeprefix('assets/')}"
        if re.match(r"^[a-z][a-z0-9+.-]*:", value, re.IGNORECASE):
            return urllib.parse.quote(value, safe=":/?&=#%+@,;\\!$'*-._~")
        if value.startswith("#"):
            return value
        return markdown_uri(value)

    def _style(self, node: HtmlNode) -> dict[str, str]:
        return parse_style(node.attrs.get("style", ""))

    def _is_monospace(self, node: HtmlNode) -> bool:
        family = self._style(node).get("font-family", "").lower()
        if any(name in family for name in MONOSPACE_FONTS):
            return True
        return any(self._is_monospace(child) for child in node.child_nodes())

    def _max_font_size(self, node: HtmlNode) -> float:
        sizes: list[float] = []
        size = numeric_css(self._style(node).get("font-size"))
        if size is not None:
            sizes.append(size)
        for child in node.child_nodes():
            sizes.append(self._max_font_size(child))
        return max(sizes, default=0.0)

    def _apply_inline_style(self, node: HtmlNode, value: str) -> str:
        if not value.strip():
            return value
        style = self._style(node)
        tag = node.tag
        weight = style.get("font-weight", "").lower()
        bold = tag in {"b", "strong"} or weight == "bold" or (weight.isdigit() and int(weight) >= 600)
        italic = tag in {"i", "em"} or style.get("font-style", "").lower() == "italic"
        decoration = style.get("text-decoration", "").lower()
        strike = tag in {"del", "s", "strike"} or "line-through" in decoration
        underline = tag == "u" or "underline" in decoration
        background = style.get("background", "") or style.get("background-color", "")
        monospace = tag in {"code", "kbd", "samp", "tt"} or any(
            name in style.get("font-family", "").lower() for name in MONOSPACE_FONTS
        )
        result = value
        if monospace and "\n" not in result:
            ticks = "``" if "`" in result else "`"
            result = f"{ticks}{result.strip()}{ticks}"
        if bold:
            result = f"**{result.strip()}**"
        if italic:
            result = f"*{result.strip()}*"
        if strike:
            result = f"~~{result.strip()}~~"
        if underline:
            result = f"<u>{result.strip()}</u>"
        if background and background.lower() not in {"transparent", "none", "#ffffff", "white"}:
            result = f"<mark>{result.strip()}</mark>"
        return result

    def render_inline(self, node: HtmlNode | str) -> str:
        if isinstance(node, str):
            return collapse_inline_space(node)
        if node.tag in SKIP_TAGS:
            return ""
        if node.tag == "br":
            return "  \n"
        if node.tag == "img":
            source = node.attrs.get("src") or node.attrs.get("data-fullres-src") or ""
            if not source:
                return ""
            alt = collapse_inline_space(node.attrs.get("alt") or node.attrs.get("title") or "").strip()
            if not alt or len(alt) > 120:
                alt = Path(urllib.parse.unquote(source)).stem or "image"
            alt = alt.replace("[", "\\[").replace("]", "\\]")
            return f"![{alt}]({self.rewrite_url(source)})"
        if node.tag == "object":
            source = node.attrs.get("data") or node.attrs.get("src") or ""
            name = node.attrs.get("data-attachment") or node.attrs.get("title") or "attachment"
            return f"[📎 {name}]({self.rewrite_url(source)})" if source else f"📎 {name}"
        if node.tag in {"iframe", "video", "audio", "embed", "source"}:
            source = node.attrs.get("src") or node.attrs.get("data") or ""
            label = node.attrs.get("title") or f"embedded {node.tag}"
            return f"[{label}]({self.rewrite_url(source)})" if source else ""
        content = "".join(self.render_inline(child) for child in node.children)
        if node.tag == "a":
            href = node.attrs.get("href", "")
            label = content.strip() or href
            if not href:
                return label
            if label == href and re.match(r"^https?://", href):
                return f"<{href}>"
            return f"[{label}]({self.rewrite_url(href)})"
        if node.tag == "sup":
            return f"<sup>{content.strip()}</sup>"
        if node.tag == "sub":
            return f"<sub>{content.strip()}</sub>"
        return self._apply_inline_style(node, content)

    def render_table(self, node: HtmlNode) -> str:
        row_nodes = list(node.descendants("tr"))
        if len(row_nodes) == 1:
            cells = [child for child in row_nodes[0].child_nodes() if child.tag in {"th", "td"}]
            if len(cells) == 1:
                paragraphs = list(cells[0].descendants("p"))
                plain_lines = [node_literal_text(paragraph) for paragraph in paragraphs if node_literal_text(paragraph)]
                if plain_lines:
                    value = "\n".join(plain_lines).replace("```", "``\u200b`")
                    return f"```\n{value}\n```\n\n"

        rows: list[list[str]] = []
        self._table_depth += 1
        try:
            for row in row_nodes:
                cells = [child for child in row.child_nodes() if child.tag in {"th", "td"}]
                if not cells:
                    continue
                rendered = []
                for cell in cells:
                    value = normalize_markdown(self.render_children(cell)).replace("\n", "<br>")
                    rendered.append(value.replace("|", "\\|"))
                rows.append(rendered)
        finally:
            self._table_depth -= 1
        if not rows:
            return ""
        width = max(len(row) for row in rows)
        rows = [row + [""] * (width - len(row)) for row in rows]
        lines = ["| " + " | ".join(rows[0]) + " |", "| " + " | ".join(["---"] * width) + " |"]
        lines.extend("| " + " | ".join(row) + " |" for row in rows[1:])
        return "\n".join(lines) + "\n\n"

    def render_list(self, node: HtmlNode, depth: int = 0) -> str:
        ordered = node.tag == "ol"
        lines: list[str] = []
        item_index = 1
        for item in node.child_nodes("li"):
            nested = [child for child in item.child_nodes() if child.tag in {"ul", "ol"}]
            main_children = [
                child for child in item.children if not (isinstance(child, HtmlNode) and child.tag in {"ul", "ol"})
            ]
            content = normalize_markdown("".join(
                self.render_block(child) if isinstance(child, HtmlNode) and child.tag in BLOCK_TAGS
                else self.render_inline(child)
                for child in main_children
            ))
            data_tag = item.attrs.get("data-tag", "").lower()
            checkbox = ""
            if data_tag.startswith("to-do"):
                checkbox = "[x] " if "completed" in data_tag else "[ ] "
            marker = f"{item_index}." if ordered else "-"
            prefix = "  " * depth + marker + " " + checkbox
            content_lines = content.splitlines() or [""]
            lines.append(prefix + content_lines[0])
            continuation = "  " * (depth + 1)
            lines.extend(continuation + line for line in content_lines[1:])
            for child_list in nested:
                lines.append(self.render_list(child_list, depth + 1).rstrip())
            item_index += 1
        return "\n".join(lines) + "\n\n"

    @staticmethod
    def _paragraph_line(node: HtmlNode | str) -> str | None:
        if not isinstance(node, HtmlNode) or node.tag != "p":
            return None
        return node_literal_text(node).strip()

    @staticmethod
    def _has_internal_link(node: HtmlNode | str) -> bool:
        return isinstance(node, HtmlNode) and any(
            is_onenote_internal_url(link.attrs.get("href", ""))
            for link in node.descendants("a")
        )

    def _range_has_internal_link(
        self,
        children: list[HtmlNode | str],
        start: int,
        end: int,
    ) -> bool:
        return any(self._has_internal_link(child) for child in children[start:end + 1])

    def _shell_review(self, reason: str, value: str) -> None:
        key = (reason, value)
        if key in self._shell_review_keys:
            return
        self._shell_review_keys.add(key)
        self.shell_reviews.append({"reason": reason, "text": value})

    @staticmethod
    def _ambiguous_shell_candidate(value: str) -> bool:
        had_prompt = bool(re.match(r"^(?:(?:\$|#)\s+|#(?=sudo\b))", value.strip()))
        line = shell_prompt_body(value)
        match = re.match(r"^([A-Za-z][A-Za-z0-9_.+-]*)(?:\s+([^\s]+))?", line)
        if not match:
            return False
        command = match.group(1).lower()
        argument = (match.group(2) or "").lower()
        known = command in SHELL_COMMANDS_WITH_SUBCOMMANDS or command in SHELL_COMMANDS_WITH_ARGUMENTS
        if not known or not argument:
            return False
        if command in SHELL_COMMANDS_WITH_SUBCOMMANDS:
            recognized = argument in SHELL_COMMANDS_WITH_SUBCOMMANDS[command] or argument.startswith("-")
            if not recognized:
                return False
        if command == "echo" and not had_prompt and line.rstrip().endswith(";"):
            return False
        if argument == "=":
            return False
        has_syntax = bool(re.search(r"(?:^|\s)(?:--?\w|[/~$][^\s]*|[^\s]+\.[A-Za-z0-9]+)|[|<>]", line))
        has_prose = (
            "\uFFFC" in value
            or any(marker in f" {line} " for marker in SHELL_PROSE_MARKERS)
            or "또는" in line
        )
        return has_syntax and has_prose

    @staticmethod
    def _mixed_shell_text(value: str) -> str:
        """Preserve command-plus-explanation paragraphs as readable literal text."""
        value = value.replace("\r\n", "\n").replace("\r", "\n")
        value = re.sub(r"\uFFFC+", "\n", value)
        return re.sub(r"\n{3,}", "\n\n", value).strip()

    @staticmethod
    def _heredoc_terminator(value: str, delimiter: str) -> tuple[str, bool]:
        if value == delimiter:
            return "", True
        embedded = re.match(rf"^(.*?)(?:\uFFFC)+{re.escape(delimiter)}$", value)
        return (embedded.group(1).rstrip(), True) if embedded else (value, False)

    def _heredoc_end(self, children: list[HtmlNode | str], start: int, delimiter: str) -> int | None:
        for index in range(start + 1, len(children)):
            child = children[index]
            if isinstance(child, str):
                if child.strip():
                    return None
                continue
            if child.tag == "br":
                continue
            line = self._paragraph_line(child)
            if line is None:
                return None
            _, terminated = self._heredoc_terminator(line, delimiter)
            if terminated:
                return index
        return None

    def _shell_structure_end(
        self,
        children: list[HtmlNode | str],
        start: int,
        value: str,
    ) -> tuple[int, str] | None:
        opening = re.sub(r"^#\s*", "", value.strip())
        if not re.match(r"^(?:for\s+[A-Za-z_][A-Za-z0-9_]*\s+in\s+|while\s+)", opening):
            return None
        saw_do = bool(re.search(r";\s*do\s*$", opening))
        for index in range(start + 1, len(children)):
            child = children[index]
            if isinstance(child, str):
                if child.strip():
                    return None
                continue
            if child.tag == "br":
                continue
            line = self._paragraph_line(child)
            if line is None:
                return None
            token = line.strip()
            if token == "do":
                saw_do = True
            elif token == "done" and saw_do:
                return index, "bash"
            elif token == "end" and not saw_do:
                return index, "fish"
        return None

    @staticmethod
    def _literal_range_lines(children: list[HtmlNode | str], start: int, end: int) -> list[str]:
        lines: list[str] = []
        for child in children[start:end + 1]:
            if isinstance(child, str):
                continue
            if child.tag == "br":
                if lines and lines[-1] != "":
                    lines.append("")
                continue
            lines.extend(node_literal_text(child).rstrip().splitlines() or [""])
        while lines and not lines[-1]:
            lines.pop()
        return lines

    def _heredoc_lines(
        self,
        children: list[HtmlNode | str],
        start: int,
        end: int,
        delimiter: str,
    ) -> list[str]:
        lines: list[str] = []
        for child in children[start:end + 1]:
            if isinstance(child, str):
                continue
            if child.tag == "br":
                if lines and lines[-1] != "":
                    lines.append("")
                continue
            line = node_literal_text(child).rstrip()
            if child is children[end]:
                content, terminated = self._heredoc_terminator(line, delimiter)
                if terminated:
                    if content:
                        lines.extend(content.splitlines())
                    lines.append(delimiter)
                    continue
            lines.extend(line.splitlines() or [""])
        while lines and not lines[-1]:
            lines.pop()
        return lines

    @staticmethod
    def _next_significant(children: list[HtmlNode | str], start: int) -> int:
        index = start
        while index < len(children):
            child = children[index]
            if not (isinstance(child, str) and not child.strip()):
                break
            index += 1
        return index

    def render_children(self, node: HtmlNode) -> str:
        parts: list[str] = []
        children = node.children
        index = 0
        while index < len(children):
            child = children[index]
            if isinstance(child, str) and not child.strip() and any(character in child for character in "\r\n\t"):
                index += 1
                continue

            line = self._paragraph_line(child) if self._table_depth == 0 else None
            if (
                line
                and isinstance(child, HtmlNode)
                and (
                    self._has_internal_link(child)
                    or self._max_font_size(child) >= 15
                )
            ):
                line = None
            heredoc = HEREDOC_START.match(line) if line else None
            if heredoc:
                end = self._heredoc_end(children, index, heredoc.group(1))
                if end is not None:
                    if not self._range_has_internal_link(children, index, end):
                        values = self._heredoc_lines(children, index, end, heredoc.group(1))
                        parts.append(fenced_code("\n".join(values), "bash") + "\n\n")
                        self.shell_code_blocks += 1
                        index = end + 1
                        continue
                else:
                    self._shell_review("heredoc 시작은 있지만 종료 표식을 찾지 못함", line)

            structure = self._shell_structure_end(children, index, line) if line else None
            if structure and not self._range_has_internal_link(children, index, structure[0]):
                end, language = structure
                values = self._literal_range_lines(children, index, end)
                parts.append(fenced_code("\n".join(values), language) + "\n\n")
                self.shell_code_blocks += 1
                index = end + 1
                continue

            if line and obvious_shell_command(line):
                command_lines = [line]
                cursor = self._next_significant(children, index + 1)
                while cursor < len(children):
                    if self._has_internal_link(children[cursor]):
                        break
                    next_line = self._paragraph_line(children[cursor])
                    continuation = command_lines[-1].rstrip().endswith("\\")
                    if not next_line or (not continuation and not obvious_shell_command(next_line)):
                        break
                    command_lines.append(next_line)
                    cursor = self._next_significant(children, cursor + 1)
                if len(command_lines) == 1:
                    parts.append(inline_code(line) + "\n\n")
                    self.inline_shell_commands += 1
                else:
                    parts.append(fenced_code("\n".join(command_lines), shell_language(command_lines)) + "\n\n")
                    self.shell_code_blocks += 1
                index = cursor
                continue

            if line and self._ambiguous_shell_candidate(line):
                parts.append(fenced_code(self._mixed_shell_text(line), "text") + "\n\n")
                self.shell_code_blocks += 1
                index += 1
                continue

            if isinstance(child, HtmlNode) and child.tag in BLOCK_TAGS:
                parts.append(self.render_block(child))
            else:
                parts.append(self.render_inline(child))
            index += 1
        return "".join(parts)

    def render_block(self, node: HtmlNode | str) -> str:
        if isinstance(node, str):
            text = collapse_inline_space(node)
            return text if text.strip() else ""
        if node.tag in SKIP_TAGS:
            return ""
        if node.tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            level = int(node.tag[1])
            return f"{'#' * level} {normalize_markdown(self.render_children(node))}\n\n"
        if node.tag == "hr":
            return "---\n\n"
        if node.tag == "pre":
            value = node_text(node).replace("```", "``\u200b`")
            return f"```\n{value}\n```\n\n"
        if node.tag in {"ul", "ol"}:
            return self.render_list(node)
        if node.tag == "table":
            return self.render_table(node)
        if node.tag == "blockquote":
            value = normalize_markdown(self.render_children(node))
            return "\n".join("> " + line if line else ">" for line in value.splitlines()) + "\n\n"
        if node.tag in {"p", "div", "section", "article", "figure", "aside"}:
            value = normalize_markdown(self.render_children(node))
            if not value:
                return ""
            data_tag = node.attrs.get("data-tag", "").lower()
            if data_tag.startswith("to-do"):
                checked = "x" if "completed" in data_tag else " "
                return f"- [{checked}] {value}\n\n"
            if data_tag == "remember-for-later":
                return "> [!note] 기억할 항목\n" + "\n".join("> " + line for line in value.splitlines()) + "\n\n"
            if self._is_monospace(node) and ("\n" in value or len(value) > 80):
                value = value.replace("```", "``\u200b`")
                return f"```\n{value}\n```\n\n"
            if node.tag == "p" and "\n" not in value:
                size = self._max_font_size(node)
                if size >= 18:
                    return f"## {value}\n\n"
                if size >= 15:
                    return f"### {value}\n\n"
            return value + "\n\n"
        if node.tag in {"img", "object", "iframe", "video", "audio", "embed"}:
            value = self.render_inline(node)
            return value + "\n\n" if value else ""
        return self.render_children(node)

    def _position(self, node: HtmlNode) -> tuple[float, float, float | None] | None:
        style = self._style(node)
        if style.get("position", "").lower() != "absolute":
            return None
        top = numeric_css(style.get("top"))
        left = numeric_css(style.get("left"))
        width = numeric_css(style.get("width"))
        if top is None or left is None:
            return None
        return top, left, width

    @staticmethod
    def position_key(position: tuple[float, float, float | None] | None, index: int) -> str:
        if position is None:
            return f"flow:{index}"
        top, left, _ = position
        return f"{top:g},{left:g}"

    def parse_blocks(self, source: str) -> list[RenderedBlock]:
        parser = OneNoteHtmlParser()
        parser.feed(source)
        body = next(parser.root.descendants("body"), parser.root)
        children = [child for child in body.children if isinstance(child, HtmlNode) and child.tag not in SKIP_TAGS]
        positioned = [(index, child, self._position(child)) for index, child in enumerate(children)]
        if children and all(position is not None for _, _, position in positioned):
            positioned.sort(key=lambda item: (item[2][0], item[2][1]))  # type: ignore[index]
        blocks: list[RenderedBlock] = []
        for index, child, position in positioned:
            rendered = normalize_markdown(self.render_block(child))
            if not rendered:
                continue
            blocks.append(RenderedBlock(
                key=self.position_key(position, index),
                node=child,
                markdown=rendered,
                literal=node_literal_text(child),
                position=position,
            ))
        if not children:
            rendered = normalize_markdown(self.render_children(body))
            if rendered:
                blocks.append(RenderedBlock("flow:0", body, rendered, node_literal_text(body), None))
        return blocks

    def render_document(self, source: str) -> tuple[str, int]:
        blocks = self.parse_blocks(source)
        notes = 0
        parts: list[str] = []
        previous_position: tuple[float, float, float | None] | None = None
        previous_rendered = ""
        for block in blocks:
            position = block.position
            rendered = block.markdown
            annotation = False
            if position is not None and previous_position is not None:
                top, left, width = position
                previous_top, previous_left, previous_width = previous_position
                right_edge = previous_left + (previous_width or 300)
                annotation = abs(top - previous_top) <= 90 and left >= right_edge - 20 and len(block.literal) <= 600
            if position is not None:
                top, left, width = position
                parts.append(f"<!-- onenote-position: top={top:g} left={left:g} width={width if width is not None else 'unknown'} -->")
            if annotation:
                notes += 1
                review_id = f"{self.review_id_prefix}-{notes:02d}"
                self.layout_reviews.append({
                    "reviewId": review_id,
                    "candidateTarget": {
                        "top": previous_position[0],
                        "left": previous_position[1],
                        "width": previous_position[2],
                        "markdown": review_excerpt(previous_rendered),
                    },
                    "annotation": {
                        "top": position[0],
                        "left": position[1],
                        "width": position[2],
                        "markdown": review_excerpt(rendered),
                    },
                })
                parts.append(f'<a id="layout-review-{review_id}"></a>')
                quoted = "\n".join("> " + line if line else ">" for line in rendered.splitlines())
                parts.append("> [!note] OneNote 자유 배치 메모\n" + quoted)
            else:
                parts.append(rendered)
            if position is not None:
                previous_position = position
                previous_rendered = rendered
        return normalize_markdown("\n\n".join(parts)), notes


@dataclass
class PageEntry:
    source_dir: Path
    metadata: dict[str, object]
    children: list[PageEntry] = field(default_factory=list)

    @property
    def page_id(self) -> str:
        return str(self.metadata.get("id") or self.source_dir.name)

    @property
    def title(self) -> str:
        return str(self.metadata.get("title") or "untitled")

    @property
    def level(self) -> int:
        try:
            return max(0, int(self.metadata.get("level") or 0))
        except (TypeError, ValueError):
            return 0

    @property
    def order(self) -> int:
        try:
            return int(self.metadata.get("order") or 0)
        except (TypeError, ValueError):
            return 0


def build_page_tree(section_dir: Path, warnings: list[str]) -> list[PageEntry]:
    pages: list[PageEntry] = []
    for metadata_path in section_dir.glob("*/page.json"):
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            warnings.append(f"page metadata unreadable: {metadata_path}: {error}")
            continue
        pages.append(PageEntry(metadata_path.parent, metadata))
    pages.sort(key=lambda page: (page.order, page.source_dir.name))
    roots: list[PageEntry] = []
    stack: list[PageEntry] = []
    for page in pages:
        level = page.level
        if level > len(stack):
            warnings.append(f"page level gap normalized: {page.source_dir} level={level} expected<={len(stack)}")
            level = len(stack)
        del stack[level:]
        if level == 0:
            roots.append(page)
        else:
            stack[level - 1].children.append(page)
        stack.append(page)
    return roots


class NameAllocator:
    def __init__(self) -> None:
        self.used: dict[Path, dict[str, str]] = {}

    def allocate(self, parent: Path, desired: str, source_key: str) -> str:
        names = self.used.setdefault(parent, {})
        candidate = desired
        folded = candidate.casefold()
        if folded in names and names[folded] != source_key:
            candidate = f"{desired}--{stable_short(source_key)}"
            folded = candidate.casefold()
        names[folded] = source_key
        return candidate


class Converter:
    def __init__(self, project_root: Path, config_path: Path, replace: bool = False) -> None:
        self.project_root = project_root
        self.config_path = config_path
        self.replace = replace
        self.config = json.loads(config_path.read_text(encoding="utf-8"))
        self.silverbullet_root = str(self.config.get("silverBulletRoot") or "").strip().strip("/")
        if self.silverbullet_root and any(
            part in {"", ".", ".."} for part in Path(self.silverbullet_root).parts
        ):
            raise RuntimeError(f"invalid silverBulletRoot: {self.silverbullet_root}")
        self.allowed = {str(item["id"]): str(item["name"]) for item in self.config.get("notebooks", [])}
        if not self.allowed:
            raise RuntimeError("markdown allowlist is empty")
        override_payload = self.config.get("internalLinkOverrides", {})
        if not isinstance(override_payload, dict):
            raise RuntimeError("internalLinkOverrides must be an object keyed by classic OneNote GUID")
        self.internal_link_overrides = {
            normalize_legacy_onenote_id(str(link_id).removeprefix("page:")): Path(str(target))
            for link_id, target in override_payload.items()
            if not str(link_id).startswith("section:")
        }
        self.internal_section_link_overrides = {
            normalize_legacy_onenote_id(str(link_id).removeprefix("section:")): Path(str(target))
            for link_id, target in override_payload.items()
            if str(link_id).startswith("section:")
        }
        self.source_root = self._resolve_config_path(str(self.config.get("sourceArchiveRoot") or "./output/archive"))
        self.output_root = self._resolve_config_path(str(self.config.get("outputRoot") or "./output/markdown"))
        self.curation_path: Path | None = None
        self.curations: dict[str, dict[str, object]] = {}
        curation_value = self.config.get("curationFile")
        if curation_value:
            self.curation_path = self._resolve_config_path(str(curation_value))
            if not self.curation_path.is_file():
                raise RuntimeError(f"curation file does not exist: {self.curation_path}")
            curation_payload = json.loads(self.curation_path.read_text(encoding="utf-8"))
            pages = curation_payload.get("pages", {})
            if not isinstance(pages, dict):
                raise RuntimeError("curation pages must be an object keyed by OneNote page ID")
            self.curations = {
                str(page_id): value
                for page_id, value in pages.items()
                if isinstance(value, dict)
            }
        self.allocator = NameAllocator()
        self.warnings: list[str] = []
        self.mapping: list[dict[str, object]] = []
        self.layout_reviews: list[dict[str, object]] = []
        self.shell_reviews: list[dict[str, object]] = []
        self.stats: dict[str, int] = {
            "notebooks": 0,
            "sections": 0,
            "pages": 0,
            "oldPages": 0,
            "visualReviewPages": 0,
            "layoutNotes": 0,
            "incompleteArchivePages": 0,
            "reconciledArchivePages": 0,
            "unlocalizedResourcePages": 0,
            "unlocalizedResources": 0,
            "assets": 0,
            "assetBytes": 0,
            "internalLinksFound": 0,
            "internalLinksRewritten": 0,
            "internalPageLinks": 0,
            "internalSectionLinks": 0,
            "internalLinkOverrides": 0,
            "unresolvedInternalLinks": 0,
            "shellCodeBlocks": 0,
            "inlineShellCommands": 0,
            "shellReviewCandidates": 0,
        }
        self.document_extensions: Counter[str] = Counter()
        self.tag_counts: Counter[str] = Counter()
        self.internal_link_report: list[dict[str, object]] = []
        self.staging_root: Path | None = None

    def _resolve_config_path(self, value: str) -> Path:
        path = Path(value).expanduser()
        return path.resolve() if path.is_absolute() else (self.project_root / path).resolve()

    def _page_ref(self, source: Path, target: Path) -> str:
        if source.is_absolute():
            if self.staging_root is None:
                raise RuntimeError("staging root is not initialized")
            source = source.relative_to(self.staging_root)
        if target.is_absolute():
            if self.staging_root is None:
                raise RuntimeError("staging root is not initialized")
            target = target.relative_to(self.staging_root)
        return silverbullet_page_ref(source, target, self.silverbullet_root)

    def discover_notebooks(self) -> list[tuple[Path, dict[str, object], str]]:
        discovered: dict[str, tuple[Path, dict[str, object]]] = {}
        for metadata_path in self.source_root.glob("*/notebook.json"):
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            notebook_id = str(metadata.get("id") or "")
            if notebook_id in self.allowed:
                discovered[notebook_id] = (metadata_path.parent, metadata)
        missing = sorted(set(self.allowed) - set(discovered))
        if missing:
            raise RuntimeError(f"allowlisted notebooks missing from archive: {len(missing)}")
        return [(discovered[item_id][0], discovered[item_id][1], self.allowed[item_id]) for item_id in self.allowed]

    def copy_assets(self, source_dir: Path, destination_dir: Path) -> tuple[int, int, Counter[str]]:
        source_assets = source_dir / "assets"
        if not source_assets.is_dir():
            return 0, 0, Counter()
        count = 0
        size = 0
        extensions: Counter[str] = Counter()
        for source in source_assets.rglob("*"):
            if not source.is_file() or source.name.endswith(".part"):
                continue
            relative = source.relative_to(source_assets)
            destination = destination_dir / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            count += 1
            size += source.stat().st_size
            extension = source.suffix.lower().lstrip(".") or "no-extension"
            extensions[extension] += 1
            self.document_extensions[extension] += 1
        return count, size, extensions

    @staticmethod
    def page_tags(
        notebook_name: str,
        section_name: str,
        old: bool,
        needs_visual_review: bool,
        curated: bool,
        extensions: Counter[str],
    ) -> list[str]:
        tags = [
            "source/onenote",
            "type/note",
            f"notebook/{tag_component(notebook_name)}",
            f"section/{tag_component(section_name)}",
            "status/old" if old else "status/current",
            "rag/fallback" if old else "rag/normal",
        ]
        if curated:
            tags.append("layout/curated")
        elif needs_visual_review:
            tags.append("layout/review")
        else:
            tags.append("layout/automatic")
        if extensions:
            tags.append("has/document")
            extension_names = set(extensions)
            if extension_names & IMAGE_EXTENSIONS:
                tags.append("document/image")
            if extension_names & VIDEO_EXTENSIONS:
                tags.append("document/video")
            if extension_names & AUDIO_EXTENSIONS:
                tags.append("document/audio")
            if "pdf" in extension_names:
                tags.append("document/pdf")
            known = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS | AUDIO_EXTENSIONS | {"pdf"}
            if extension_names - known:
                tags.append("document/attachment")
        return tags

    @staticmethod
    def _quote_callout(value: str, kind: str, title: str) -> str:
        lines = [f"> [!{kind}] {title}"]
        lines.extend("> " + line if line else ">" for line in value.splitlines())
        return "\n".join(lines)

    @staticmethod
    def _block_map(blocks: list[RenderedBlock]) -> dict[str, RenderedBlock]:
        result: dict[str, RenderedBlock] = {}
        for block in blocks:
            if block.key in result:
                raise RuntimeError(f"duplicate OneNote layout coordinate: {block.key}")
            result[block.key] = block
        return result

    @staticmethod
    def _table_rows(table: HtmlNode) -> list[list[HtmlNode]]:
        rows: list[list[HtmlNode]] = []
        for row in table.descendants("tr"):
            nearest_table = row.parent
            while nearest_table is not None and nearest_table.tag != "table":
                nearest_table = nearest_table.parent
            if nearest_table is not table:
                continue
            cells = [child for child in row.child_nodes() if child.tag in {"th", "td"}]
            if cells:
                rows.append(cells)
        return rows

    def _table_cell_node(self, block: RenderedBlock, table_index: int, row: int, column: int) -> HtmlNode:
        tables = ([block.node] if block.node.tag == "table" else []) + list(block.node.descendants("table"))
        if table_index < 0 or table_index >= len(tables):
            raise RuntimeError(f"table index out of range for block {block.key}: {table_index}")
        rows = self._table_rows(tables[table_index])
        if row < 0 or row >= len(rows) or column < 0 or column >= len(rows[row]):
            raise RuntimeError(
                f"table cell out of range for block {block.key}: table={table_index} row={row} column={column}"
            )
        return rows[row][column]

    def _cell_value(
        self,
        cell: object,
        block_map: dict[str, RenderedBlock],
        renderer: MarkdownRenderer,
        referenced: set[str],
    ) -> tuple[str, bool]:
        if isinstance(cell, str):
            return cell, False
        if not isinstance(cell, dict):
            raise RuntimeError("curation table cell must be a string or object")
        if "text" in cell:
            return str(cell.get("text") or ""), bool(cell.get("code"))
        key = str(cell.get("block") or "")
        if key not in block_map:
            raise RuntimeError(f"curation references missing block: {key}")
        referenced.add(key)
        block = block_map[key]
        node = block.node
        if "tableCell" in cell:
            selector = cell["tableCell"]
            if not isinstance(selector, dict):
                raise RuntimeError("tableCell selector must be an object")
            node = self._table_cell_node(
                block,
                int(selector.get("table", 0)),
                int(selector.get("row", 0)),
                int(selector.get("column", 0)),
            )
        mode = str(cell.get("mode") or "literal")
        if mode == "markdown":
            return normalize_markdown(renderer.render_children(node)), False
        if mode != "literal":
            raise RuntimeError(f"unsupported curation table cell mode: {mode}")
        return node_literal_text(node), True

    def _render_curated_block(self, block: RenderedBlock, item: dict[str, object]) -> str:
        mode = str(item.get("mode") or "markdown")
        if mode == "markdown":
            value = block.markdown
        elif mode == "code":
            lines = block.literal.splitlines()
            drop_lines = int(item.get("dropLeadingLines") or 0)
            value = fenced_text("\n".join(lines[drop_lines:]).strip())
        elif mode in {"note", "warning"}:
            value = self._quote_callout(
                block.markdown,
                mode,
                str(item.get("calloutTitle") or ("참고" if mode == "note" else "주의")),
            )
        else:
            raise RuntimeError(f"unsupported curated block mode: {mode}")
        heading = str(item.get("heading") or "").strip()
        return f"{heading}\n\n{value}" if heading else value

    def render_curated_body(
        self,
        renderer: MarkdownRenderer,
        blocks: list[RenderedBlock],
        curation: dict[str, object],
        page_id: str,
    ) -> str:
        block_map = self._block_map(blocks)
        referenced: set[str] = set()

        for replacement in curation.get("replacements", []):
            if not isinstance(replacement, dict):
                raise RuntimeError(f"invalid replacement for curated page {page_id}")
            key = str(replacement.get("block") or "")
            if key not in block_map:
                raise RuntimeError(f"curation replacement references missing block: {key}")
            find = str(replacement.get("find") or "")
            replace = str(replacement.get("replace") or "")
            if not find or find not in block_map[key].markdown:
                raise RuntimeError(f"curation replacement text not found in block {key} for page {page_id}")
            block_map[key].markdown = block_map[key].markdown.replace(find, replace, 1)

        for insertion in curation.get("insertions", []):
            if not isinstance(insertion, dict):
                raise RuntimeError(f"invalid insertion for curated page {page_id}")
            target_key = str(insertion.get("target") or "")
            source_key = str(insertion.get("source") or "")
            if target_key not in block_map or source_key not in block_map:
                raise RuntimeError(f"curation insertion references missing block for page {page_id}")
            marker = str(insertion.get("after") or "")
            target = block_map[target_key]
            if not marker or marker not in target.markdown:
                raise RuntimeError(f"curation insertion marker not found in block {target_key} for page {page_id}")
            fragment = self._render_curated_block(block_map[source_key], insertion)
            target.markdown = target.markdown.replace(marker, marker + "\n\n" + fragment, 1)
            referenced.add(source_key)

        parts: list[str] = []
        layout = curation.get("layout", [])
        if not isinstance(layout, list) or not layout:
            raise RuntimeError(f"curated page has no layout: {page_id}")
        for item in layout:
            if not isinstance(item, dict):
                raise RuntimeError(f"curation layout item must be an object: {page_id}")
            item_type = str(item.get("type") or "block")
            if item_type == "markdown":
                parts.append(str(item.get("text") or ""))
                continue
            if item_type == "block":
                key = str(item.get("block") or "")
                if key not in block_map:
                    raise RuntimeError(f"curation references missing block: {key}")
                referenced.add(key)
                parts.append(self._render_curated_block(block_map[key], item))
                continue
            if item_type == "blocks":
                keys = [str(value) for value in item.get("blocks", [])]
                missing = [key for key in keys if key not in block_map]
                if missing:
                    raise RuntimeError(f"curation references missing blocks: {', '.join(missing)}")
                referenced.update(keys)
                value = "\n\n".join(block_map[key].markdown for key in keys)
                if item.get("history"):
                    marker = str(item.get("historyMarker") or "이 아래 내용은 이전 시도 또는 실패 기록입니다.")
                    value = f"<!-- rag-priority: fallback -->\n\n> [!warning] 히스토리\n> {marker}\n\n{value}"
                heading = str(item.get("heading") or "").strip()
                parts.append(f"{heading}\n\n{value}" if heading else value)
                continue
            if item_type == "table":
                headers = [str(value) for value in item.get("headers", [])]
                rows = item.get("rows", [])
                if not isinstance(rows, list):
                    raise RuntimeError(f"curation table rows must be a list: {page_id}")
                lines = ["<table>"]
                if headers:
                    lines.extend(["<thead><tr>", *[f"<th>{html.escape(value)}</th>" for value in headers], "</tr></thead>"])
                lines.append("<tbody>")
                for row in rows:
                    if not isinstance(row, list):
                        raise RuntimeError(f"curation table row must be a list: {page_id}")
                    lines.append("<tr>")
                    for cell in row:
                        value, code = self._cell_value(cell, block_map, renderer, referenced)
                        colspan = int(cell.get("colspan", 1)) if isinstance(cell, dict) else 1
                        colspan_attr = f' colspan="{colspan}"' if colspan > 1 else ""
                        if code:
                            encoded = html.escape(value).replace("\n", "&#10;")
                            rendered = f"<pre><code>{encoded}</code></pre>"
                        else:
                            rendered = value
                        lines.append(f"<td{colspan_attr}>{rendered}</td>")
                    lines.append("</tr>")
                lines.extend(["</tbody>", "</table>"])
                heading = str(item.get("heading") or "").strip()
                table_value = "\n".join(lines)
                parts.append(f"{heading}\n\n{table_value}" if heading else table_value)
                continue
            raise RuntimeError(f"unsupported curation layout item type: {item_type}")

        discarded = {
            str(item.get("block"))
            for item in curation.get("discard", [])
            if isinstance(item, dict) and item.get("block")
        }
        unknown_discard = discarded - set(block_map)
        if unknown_discard:
            raise RuntimeError(f"curation discards missing blocks: {', '.join(sorted(unknown_discard))}")
        unaccounted = set(block_map) - referenced - discarded
        if unaccounted:
            raise RuntimeError(
                f"curation leaves OneNote blocks unaccounted for on page {page_id}: {', '.join(sorted(unaccounted))}"
            )
        return normalize_markdown("\n\n".join(parts))

    def write_page(
        self,
        page: PageEntry,
        output_parent: Path,
        notebook_id: str,
        notebook_name: str,
        section_name: str,
        inherited_old: bool,
        relative_parent: Path,
        section_markdown: Path,
    ) -> None:
        own_old = is_old_name(page.title)
        old = inherited_old or own_old
        base_parent = output_parent
        relative_base = relative_parent
        if own_old and not inherited_old:
            base_parent = output_parent / "_old"
            relative_base = relative_parent / "_old"
        base_parent.mkdir(parents=True, exist_ok=True)
        desired = current_page_name(page.title, fallback=f"untitled-{stable_short(page.page_id)}")
        name = self.allocator.allocate(base_parent, desired, page.page_id)
        if page.children:
            page_container = base_parent / name
            markdown_path = page_container / "index.md"
            asset_dir = page_container / "_assets"
            asset_prefix = "_assets"
            relative_markdown = relative_base / name / "index.md"
            child_parent = page_container
            child_relative = relative_base / name
        else:
            markdown_path = base_parent / f"{name}.md"
            asset_dir = base_parent / f"{name}.assets"
            asset_prefix = f"{name}.assets"
            relative_markdown = relative_base / f"{name}.md"
            child_parent = base_parent
            child_relative = relative_base
        markdown_path.parent.mkdir(parents=True, exist_ok=True)

        local_html_path = page.source_dir / "page.local.html"
        if not local_html_path.is_file():
            self.warnings.append(f"missing page.local.html: {page.source_dir}")
            return
        local_html = local_html_path.read_text(encoding="utf-8", errors="replace")
        unlocalized_resources = unlocalized_onenote_resource_ids(local_html)
        renderer = MarkdownRenderer(asset_prefix, review_id_prefix=stable_short(page.page_id, 12))
        curation = self.curations.get(page.page_id)
        if curation:
            blocks = renderer.parse_blocks(local_html)
            body = self.render_curated_body(renderer, blocks, curation, page.page_id)
            layout_note_count = 0
        else:
            body, layout_note_count = renderer.render_document(local_html)
        assets, asset_bytes, document_extensions = self.copy_assets(page.source_dir, asset_dir)
        if assets == 0 and asset_dir.exists():
            asset_dir.rmdir()

        source_archive_status = str(page.metadata.get("archiveStatus") or "complete")
        failed_resources = [
            resource for resource in page.metadata.get("resources", [])
            if isinstance(resource, dict) and resource.get("status") == "failed"
        ]
        unresolved_failed_resources = []
        for resource in failed_resources:
            file_name = str(resource.get("fileName") or "")
            local_resource = page.source_dir / "assets" / file_name
            if not file_name or not local_resource.is_file() or local_resource.stat().st_size == 0:
                unresolved_failed_resources.append(resource)
        archive_status = source_archive_status
        if source_archive_status != "complete" and failed_resources and not unresolved_failed_resources:
            archive_status = "complete"
        if unlocalized_resources:
            archive_status = "incomplete"
        needs_visual_review = bool(page.metadata.get("needsVisualReview")) and not bool(
            curation and curation.get("resolved", True)
        )
        tags = self.page_tags(
            notebook_name,
            section_name,
            old,
            needs_visual_review,
            bool(curation),
            document_extensions,
        )
        self.tag_counts.update(tags)
        layout_status = "curated" if curation else ("review" if needs_visual_review else "automatic")
        header = front_matter([
            ("title", page.title),
            ("tags", " ".join(tags)),
            ("source_system", "onenote"),
            ("content_type", "note"),
            ("onenote_id", page.page_id),
            ("onenote_notebook_id", notebook_id),
            ("notebook", notebook_name),
            ("section", section_name),
            ("created", page.metadata.get("createdDateTime")),
            ("modified", page.metadata.get("lastModifiedDateTime")),
            ("status", "old" if old else "current"),
            ("rag_priority", "fallback" if old else "normal"),
            ("needs_visual_review", needs_visual_review),
            ("layout_curated", bool(curation)),
            ("layout_status", layout_status),
            ("archive_status", archive_status),
            ("source_archive_status", source_archive_status),
            ("unlocalized_onenote_resources", len(unlocalized_resources)),
            ("onenote_level", page.level),
            ("onenote_order", page.order),
            ("document_count", assets),
            ("document_bytes", asset_bytes),
            ("document_types", " ".join(sorted(document_extensions)) or "none"),
        ])
        content_parts = [header, f"# {page.title}\n"]
        if archive_status != "complete" or unresolved_failed_resources or unlocalized_resources:
            missing_details = []
            if unresolved_failed_resources:
                missing_details.append(
                    "받지 못한 파일: "
                    + ", ".join(str(resource.get("fileName") or "unknown") for resource in unresolved_failed_resources)
                )
            if unlocalized_resources:
                missing_details.append(
                    f"로컬 HTML에 OneNote 원격 리소스 URL {len(unlocalized_resources)}개가 남아 있음"
                )
            content_parts.append(
                "> [!warning] OneNote 아카이브 일부 누락\n"
                "> 본문은 변환했지만 리소스 검사가 필요합니다: "
                + "; ".join(missing_details or ["아카이브 상태가 incomplete임"])
                + "\n"
            )
        if body:
            content_parts.append(body + "\n")
        else:
            content_parts.append("_빈 페이지_\n")
        markdown_path.write_text("\n".join(content_parts).rstrip() + "\n", encoding="utf-8")

        self.stats["pages"] += 1
        self.stats["assets"] += assets
        self.stats["assetBytes"] += asset_bytes
        self.stats["layoutNotes"] += layout_note_count
        self.stats["shellCodeBlocks"] += renderer.shell_code_blocks
        self.stats["inlineShellCommands"] += renderer.inline_shell_commands
        if old:
            self.stats["oldPages"] += 1
        if needs_visual_review:
            self.stats["visualReviewPages"] += 1
        if archive_status != "complete" or unresolved_failed_resources:
            self.stats["incompleteArchivePages"] += 1
        if source_archive_status != "complete" and archive_status == "complete":
            self.stats["reconciledArchivePages"] += 1
        if unlocalized_resources:
            self.stats["unlocalizedResourcePages"] += 1
            self.stats["unlocalizedResources"] += len(unlocalized_resources)
        one_note_client_url = str(
            ((page.metadata.get("links") or {}).get("oneNoteClientUrl") or {}).get("href") or ""
        )
        legacy_section_id, legacy_page_id = onenote_link_ids(one_note_client_url)
        self.mapping.append({
            "pageId": page.page_id,
            "legacyPageId": legacy_page_id,
            "legacySectionId": legacy_section_id,
            "notebookId": notebook_id,
            "source": str(page.source_dir.relative_to(self.source_root)),
            "markdown": relative_markdown.as_posix(),
            "sectionMarkdown": section_markdown.as_posix(),
            "title": page.title,
            "status": "old" if old else "current",
            "ragPriority": "fallback" if old else "normal",
            "archiveStatus": archive_status,
            "sourceArchiveStatus": source_archive_status,
            "unlocalizedOneNoteResources": len(unlocalized_resources),
            "layoutCurated": bool(curation),
        })
        for review in renderer.layout_reviews:
            self.layout_reviews.append({
                "reviewId": review["reviewId"],
                "status": "pending",
                "pageId": page.page_id,
                "notebookId": notebook_id,
                "notebook": notebook_name,
                "section": section_name,
                "title": page.title,
                "markdown": relative_markdown.as_posix(),
                "candidateTarget": review["candidateTarget"],
                "annotation": review["annotation"],
            })
        for review in renderer.shell_reviews:
            self.shell_reviews.append({
                "status": "pending",
                "pageId": page.page_id,
                "notebookId": notebook_id,
                "notebook": notebook_name,
                "section": section_name,
                "title": page.title,
                "markdown": relative_markdown.as_posix(),
                "reason": review["reason"],
                "text": review["text"],
            })
        self.stats["shellReviewCandidates"] += len(renderer.shell_reviews)

        for child in page.children:
            self.write_page(
                child,
                child_parent,
                notebook_id,
                notebook_name,
                section_name,
                old,
                child_relative,
                section_markdown,
            )

    def section_output_path(
        self,
        notebook_source: Path,
        notebook_output: Path,
        notebook_relative: Path,
        section_metadata_path: Path,
        notebook_old: bool,
    ) -> tuple[Path, Path, bool, str]:
        section_source = section_metadata_path.parent
        relative_parts = section_source.relative_to(notebook_source).parts
        current_output = notebook_output
        current_relative = notebook_relative
        inherited_old = notebook_old
        section_name = ""
        cumulative = notebook_source
        for index, raw_part in enumerate(relative_parts):
            cumulative = cumulative / raw_part
            is_section = index == len(relative_parts) - 1
            if is_section:
                metadata = json.loads(section_metadata_path.read_text(encoding="utf-8"))
                display = str(metadata.get("displayName") or archive_display_name(raw_part))
                source_key = str(metadata.get("id") or cumulative)
                section_name = display
            else:
                display = archive_display_name(raw_part)
                source_key = str(cumulative)
            own_old = is_old_name(display)
            if own_old and not inherited_old:
                current_output = current_output / "_old"
                current_relative = current_relative / "_old"
            desired = current_name(display, fallback=f"untitled-{stable_short(source_key)}")
            allocated = self.allocator.allocate(current_output, desired, source_key)
            current_output = current_output / allocated
            current_relative = current_relative / allocated
            inherited_old = inherited_old or own_old
        return current_output, current_relative, inherited_old, section_name

    def write_index(self, path: Path, title: str, links: list[tuple[str, Path]], kind: str) -> None:
        tags = "source/onenote index/root" if kind == "onenote-root" else "meta/onenote/index source/onenote"
        lines = [
            front_matter([
                ("title", title),
                ("displayName", title),
                ("tags", tags),
                ("type", kind),
                ("source_system", "onenote"),
                ("generated", True),
            ]),
            f"# {title}",
            "",
        ]
        for label, target in links:
            lines.append(f"- [{label}](<{self._page_ref(path, target)}>)")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    def rewrite_internal_links(self, staging: Path) -> None:
        page_pairs: dict[tuple[str, str], list[Path]] = {}
        page_ids: dict[str, list[Path]] = {}
        section_ids: dict[str, set[Path]] = {}
        for item in self.mapping:
            markdown = Path(str(item["markdown"]))
            page_id = item.get("legacyPageId")
            section_id = item.get("legacySectionId")
            if page_id:
                page_key = str(page_id)
                page_ids.setdefault(page_key, []).append(markdown)
                if section_id:
                    page_pairs.setdefault((str(section_id), page_key), []).append(markdown)
            if section_id:
                section_ids.setdefault(str(section_id), set()).add(Path(str(item["sectionMarkdown"])))

        def validated_override(target: Path, kind: str, link_id: str) -> Path:
            if target.is_absolute() or ".." in target.parts:
                raise RuntimeError(f"unsafe internal link override for {kind} {link_id}: {target}")
            if target.suffix.lower() != ".md" or not (staging / target).is_file():
                raise RuntimeError(f"internal link override target is missing for {kind} {link_id}: {target}")
            return target

        page_overrides = {
            link_id: validated_override(target, "page", link_id)
            for link_id, target in self.internal_link_overrides.items()
        }
        section_overrides = {
            link_id: validated_override(target, "section", link_id)
            for link_id, target in self.internal_section_link_overrides.items()
        }

        for markdown_path in sorted(staging.rglob("*.md")):
            source = markdown_path.relative_to(staging)
            original = markdown_path.read_text(encoding="utf-8")

            def replace_link(match: re.Match[str]) -> str:
                url = match.group("url")
                if not is_onenote_internal_url(url):
                    return match.group(0)
                self.stats["internalLinksFound"] += 1
                label = match.group("label")
                section_id, page_id = onenote_link_ids(url)
                target: Path | None = None
                resolution = ""
                reason = ""

                if page_id:
                    if page_id in page_overrides:
                        target = page_overrides[page_id]
                        resolution = "page-override"
                    elif section_id and len(page_pairs.get((section_id, page_id), [])) == 1:
                        target = page_pairs[(section_id, page_id)][0]
                        resolution = "section-page-id"
                    elif len(page_ids.get(page_id, [])) == 1:
                        target = page_ids[page_id][0]
                        resolution = "page-id"
                    elif len(page_ids.get(page_id, [])) > 1:
                        reason = "page ID is ambiguous without a matching section ID"
                    else:
                        reason = "page ID is not present in the Markdown allowlist"
                elif section_id:
                    if section_id in section_overrides:
                        target = section_overrides[section_id]
                        resolution = "section-override"
                    elif len(section_ids.get(section_id, set())) == 1:
                        target = next(iter(section_ids[section_id]))
                        resolution = "section-id"
                    elif len(section_ids.get(section_id, set())) > 1:
                        reason = "section ID maps to more than one section index"
                    else:
                        reason = "section ID is not present in the Markdown allowlist"
                else:
                    reason = "OneNote link contains neither a page ID nor a section ID"

                report_item: dict[str, object] = {
                    "source": source.as_posix(),
                    "label": label,
                    "legacySectionId": section_id,
                    "legacyPageId": page_id,
                }
                if target is None:
                    self.stats["unresolvedInternalLinks"] += 1
                    report_item.update({"status": "unresolved", "reason": reason})
                    self.internal_link_report.append(report_item)
                    return match.group(0)

                reference = self._page_ref(source, target)
                self.stats["internalLinksRewritten"] += 1
                if page_id:
                    self.stats["internalPageLinks"] += 1
                else:
                    self.stats["internalSectionLinks"] += 1
                if resolution.endswith("override"):
                    self.stats["internalLinkOverrides"] += 1
                report_item.update({
                    "status": "rewritten",
                    "resolution": resolution,
                    "target": target.as_posix(),
                    "reference": reference,
                })
                self.internal_link_report.append(report_item)
                trailing_backslashes = len(label) - len(label.rstrip("\\"))
                if trailing_backslashes % 2:
                    label += "\\"
                return f"[{label}](<{reference}>)"

            rewritten = MARKDOWN_LINK.sub(replace_link, original)
            if rewritten != original:
                markdown_path.write_text(rewritten, encoding="utf-8")

        unresolved = self.stats["unresolvedInternalLinks"]
        if unresolved:
            self.warnings.append(f"unresolved OneNote internal links: {unresolved}")

    def write_internal_link_report(self, meta_dir: Path) -> None:
        payload = {
            "schemaVersion": 1,
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "found": self.stats["internalLinksFound"],
            "rewritten": self.stats["internalLinksRewritten"],
            "unresolved": self.stats["unresolvedInternalLinks"],
            "links": self.internal_link_report,
        }
        (meta_dir / "internal-link-report.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        lines = [
            front_matter([
                ("title", "OneNote 내부 링크 변환 보고서"),
                ("tags", "meta/onenote/links source/onenote"),
                ("type", "onenote-internal-link-report"),
                ("generated", True),
            ]),
            "# OneNote 내부 링크 변환 보고서",
            "",
            f"- 발견: {self.stats['internalLinksFound']}",
            f"- SilverBullet 내부 링크로 변환: {self.stats['internalLinksRewritten']}",
            f"- 미해결: {self.stats['unresolvedInternalLinks']}",
            "",
        ]
        unresolved_items = [item for item in self.internal_link_report if item["status"] == "unresolved"]
        if unresolved_items:
            lines.extend(["## 미해결 링크", "", "| 원본 페이지 | 표시명 | 사유 |", "| --- | --- | --- |"])
            for item in unresolved_items:
                lines.append(f"| `{item['source']}` | {item['label']} | {item['reason']} |")
        else:
            lines.append("모든 OneNote 내부 링크를 변환했습니다.")
        (meta_dir / "internal-link-report.md").write_text(
            "\n".join(lines).rstrip() + "\n", encoding="utf-8"
        )

    def write_layout_review_reports(self, meta_dir: Path) -> None:
        payload = {
            "schemaVersion": 1,
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "count": len(self.layout_reviews),
            "reviews": self.layout_reviews,
        }
        (meta_dir / "layout-review.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

        lines = [
            front_matter([
                ("title", "OneNote 자유 배치 우선 검토 목록"),
                ("tags", "meta/onenote/review source/onenote layout/review"),
                ("type", "onenote-layout-review"),
                ("generated", True),
            ]),
            "# OneNote 자유 배치 우선 검토 목록",
            "",
            f"자동 변환기가 옆 블록을 주석으로 해석한 {len(self.layout_reviews)}건입니다.",
            "이 목록은 의미가 맞는지 확인하기 위한 것이며, `needs_visual_review` 전체 목록과는 다릅니다.",
            "",
        ]
        for number, review in enumerate(self.layout_reviews, start=1):
            target = review["candidateTarget"]
            annotation = review["annotation"]
            page_link = "../" + str(review["markdown"])
            anchor = f"#layout-review-{review['reviewId']}"
            lines.extend([
                f"## {number}. [{review['title']}]({markdown_uri(page_link)}{anchor})",
                "",
                f"- 상태: 미확인",
                f"- 검토 ID: `{review['reviewId']}`",
                f"- 노트북 / 섹션: `{review['notebook']}` / `{review['section']}`",
                (
                    "- 앞 블록 위치: "
                    f"top={target['top']}, left={target['left']}, width={target['width'] or 'unknown'}"
                ),
                (
                    "- 주석 후보 위치: "
                    f"top={annotation['top']}, left={annotation['left']}, width={annotation['width'] or 'unknown'}"
                ),
                "",
                "### 연결 대상으로 추정한 앞 블록",
                "",
                fenced_text(str(target["markdown"])),
                "",
                "### 주석으로 변환한 옆 블록",
                "",
                fenced_text(str(annotation["markdown"])),
                "",
            ])
        (meta_dir / "layout-review.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    def write_shell_review_reports(self, meta_dir: Path) -> None:
        payload = {
            "schemaVersion": 1,
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "count": len(self.shell_reviews),
            "reviews": self.shell_reviews,
        }
        (meta_dir / "shell-review.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        lines = [
            front_matter([
                ("title", "OneNote 셸 명령 수동 검토 목록"),
                ("tags", "meta/onenote/review source/onenote code/review"),
                ("type", "onenote-shell-review"),
                ("generated", True),
            ]),
            "# OneNote 셸 명령 수동 검토 목록",
            "",
            f"코드 블록으로 안전하게 자동 변환하지 못한 {len(self.shell_reviews)}건입니다.",
            "여러 열 표 안의 내용은 표 구조를 보존하기 위해 이 목록에도 넣지 않습니다.",
            "",
        ]
        for number, review in enumerate(self.shell_reviews, start=1):
            page_link = "../" + str(review["markdown"])
            lines.extend([
                f"## {number}. [{review['title']}]({markdown_uri(page_link)})",
                "",
                f"- 사유: {review['reason']}",
                f"- 노트북 / 섹션: `{review['notebook']}` / `{review['section']}`",
                "",
                fenced_text(str(review["text"])),
                "",
            ])
        if not self.shell_reviews:
            lines.append("수동으로 판단할 후보가 없습니다.")
        (meta_dir / "shell-review.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    def write_document_picker_guide(self, meta_dir: Path) -> None:
        lines = [
            front_matter([
                ("title", "OneNote 첨부 문서 안내"),
                ("tags", "meta/onenote/documents source/onenote has/document"),
                ("type", "onenote-document-guide"),
                ("generated", True),
            ]),
            "# OneNote 첨부 문서 안내",
            "",
            "SilverBullet의 `Navigate: Document Picker`에서 이미지·PDF·영상·첨부파일을 찾을 수 있습니다.",
            "각 첨부파일은 원래 페이지 옆의 `.assets/` 경로에 있으므로 페이지 제목이나 원본 파일명으로 검색합니다.",
            "",
            f"- 전체 문서: {self.stats['assets']}",
            f"- 전체 크기: {self.stats['assetBytes']} bytes",
            "",
            "## 확장자별 개수",
            "",
            "| 확장자 | 개수 |",
            "| --- | ---: |",
        ]
        for extension, count in sorted(self.document_extensions.items(), key=lambda item: (-item[1], item[0])):
            lines.append(f"| `{extension}` | {count} |")
        (meta_dir / "document-picker.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    def write_tag_guide(self, meta_dir: Path) -> None:
        operational_tags = [
            "source/onenote",
            "type/note",
            "status/current",
            "status/old",
            "rag/normal",
            "rag/fallback",
            "layout/automatic",
            "layout/review",
            "layout/curated",
            "has/document",
            "document/image",
            "document/pdf",
            "document/video",
            "document/audio",
            "document/attachment",
        ]
        notebook_tags = [tag for tag in self.tag_counts if tag.startswith("notebook/")]
        section_tags = [tag for tag in self.tag_counts if tag.startswith("section/")]
        lines = [
            front_matter([
                ("title", "OneNote 태그 안내"),
                ("tags", "meta/onenote/tags source/onenote"),
                ("type", "onenote-tag-guide"),
                ("generated", True),
            ]),
            "# OneNote 태그 안내",
            "",
            "Page Picker 검색어에 `#태그`를 함께 입력하면 결과를 좁힐 수 있습니다.",
            "Tag Picker는 `Ctrl-Alt-t` 또는 Page Picker에서 첫 글자로 `#`을 입력해 엽니다.",
            "",
            f"- `notebook/...`: {len(notebook_tags)}종",
            f"- `section/...`: {len(section_tags)}종",
            "",
            "## 운영 태그 현황",
            "",
            "| 태그 | 페이지 수 |",
            "| --- | ---: |",
        ]
        for tag in operational_tags:
            lines.append(f"| `#{tag}` | {self.tag_counts.get(tag, 0)} |")
        (meta_dir / "tag-guide.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    def convert(self) -> Path:
        notebooks = self.discover_notebooks()
        self.output_root.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=f".{self.output_root.name}.staging-", dir=self.output_root.parent))
        self.staging_root = staging
        root_links: list[tuple[str, Path]] = []
        try:
            for notebook_source, notebook_metadata, configured_name in notebooks:
                notebook_id = str(notebook_metadata.get("id"))
                notebook_name = configured_name
                notebook_old = is_old_name(notebook_name)
                notebook_desired = current_name(notebook_name, fallback=f"notebook-{stable_short(notebook_id)}")
                notebook_dir_name = self.allocator.allocate(staging, notebook_desired, notebook_id)
                notebook_output = staging / notebook_dir_name
                notebook_relative = Path(notebook_dir_name)
                notebook_output.mkdir(parents=True, exist_ok=True)
                section_links: list[tuple[str, Path]] = []
                for section_metadata_path in sorted(notebook_source.rglob("section.json")):
                    section_output, section_relative, section_old, section_name = self.section_output_path(
                        notebook_source,
                        notebook_output,
                        notebook_relative,
                        section_metadata_path,
                        notebook_old,
                    )
                    section_output.mkdir(parents=True, exist_ok=True)
                    roots = build_page_tree(section_metadata_path.parent, self.warnings)
                    for page in roots:
                        self.write_page(
                            page,
                            section_output,
                            notebook_id,
                            notebook_name,
                            section_name,
                            section_old,
                            section_relative,
                            section_relative / "_index.md",
                        )
                    self.stats["sections"] += 1
                    section_index = section_output / "_index.md"
                    if not section_index.exists():
                        self.write_index(section_index, section_name, [], "onenote-section")
                    section_links.append((section_name, section_index))
                notebook_index = notebook_output / "_index.md"
                self.write_index(notebook_index, notebook_name, section_links, "onenote-notebook")
                root_links.append((notebook_name, notebook_index))
                self.stats["notebooks"] += 1

            self.write_index(staging / "index.md", "OneNote", root_links, "onenote-root")
            meta_dir = staging / "_meta"
            meta_dir.mkdir(parents=True, exist_ok=True)
            self.rewrite_internal_links(staging)
            (meta_dir / "onenote-id-map.json").write_text(
                json.dumps(self.mapping, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            self.write_internal_link_report(meta_dir)
            self.write_layout_review_reports(meta_dir)
            self.write_shell_review_reports(meta_dir)
            self.write_document_picker_guide(meta_dir)
            self.write_tag_guide(meta_dir)
            report = {
                "schemaVersion": 1,
                "convertedAt": datetime.now(timezone.utc).isoformat(),
                "sourceArchiveRoot": str(self.source_root),
                "outputRoot": str(self.output_root),
                "allowedNotebookCount": len(self.allowed),
                "stats": self.stats,
                "warningCount": len(self.warnings),
                "warnings": self.warnings,
            }
            (meta_dir / "conversion-report.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            (staging / ".onenote-markdown-generated").write_text("generated\n", encoding="utf-8")

            if self.output_root.exists():
                marker = self.output_root / ".onenote-markdown-generated"
                if not self.replace:
                    raise RuntimeError(f"output already exists; rerun with --replace: {self.output_root}")
                if not marker.is_file():
                    raise RuntimeError(f"refusing to replace output without generated marker: {self.output_root}")
                shutil.rmtree(self.output_root)
            staging.rename(self.output_root)
            self.staging_root = None
            return self.output_root
        except Exception:
            if staging.exists():
                shutil.rmtree(staging)
            self.staging_root = None
            raise


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert preserved OneNote HTML to SilverBullet Markdown")
    parser.add_argument("--config", default=".local-config/markdown.json", help="private Markdown allowlist")
    parser.add_argument("--replace", action="store_true", help="replace a previously generated output directory")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    project_root = Path(__file__).resolve().parent.parent
    config_path = Path(args.config).expanduser()
    if not config_path.is_absolute():
        config_path = project_root / config_path
    converter = Converter(project_root, config_path.resolve(), replace=args.replace)
    output = converter.convert()
    print("Markdown conversion complete")
    print(f"- output: {output}")
    print(f"- notebooks: {converter.stats['notebooks']}")
    print(f"- sections: {converter.stats['sections']}")
    print(f"- pages: {converter.stats['pages']}")
    print(f"- old pages: {converter.stats['oldPages']}")
    print(f"- visual review: {converter.stats['visualReviewPages']}")
    print(f"- incomplete archives converted with warnings: {converter.stats['incompleteArchivePages']}")
    print(
        "- unlocalized OneNote resources: "
        f"{converter.stats['unlocalizedResources']} in {converter.stats['unlocalizedResourcePages']} pages"
    )
    print(
        "- internal OneNote links: "
        f"{converter.stats['internalLinksRewritten']}/{converter.stats['internalLinksFound']} rewritten, "
        f"{converter.stats['unresolvedInternalLinks']} unresolved"
    )
    print(
        "- shell code: "
        f"{converter.stats['shellCodeBlocks']} blocks, "
        f"{converter.stats['inlineShellCommands']} inline, "
        f"{converter.stats['shellReviewCandidates']} review candidates"
    )
    print(f"- assets: {converter.stats['assets']} ({converter.stats['assetBytes']} bytes)")
    print(f"- warnings: {len(converter.warnings)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
