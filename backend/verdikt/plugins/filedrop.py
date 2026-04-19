from __future__ import annotations

import hashlib
import sys
from collections.abc import Iterator
from pathlib import Path

from verdikt.core.models import ContentType, Domain, MaterialItem
from verdikt.plugins.base import PluginBase

_EXT_TO_CONTENT_TYPE: dict[str, ContentType] = {
    ".txt": ContentType.PLAIN,
    ".md": ContentType.MARKDOWN,
    ".html": ContentType.HTML,
    ".htm": ContentType.HTML,
    ".epub": ContentType.EPUB,
    ".pdf": ContentType.PDF,
}


class FileDropPlugin(PluginBase):
    """Ingests local files from a directory.

    Supported formats: .txt, .epub, .pdf, .html, .htm, .md
    One MaterialItem is emitted per file.
    """

    plugin_name = "filedrop"
    SUPPORTED_EXTENSIONS = set(_EXT_TO_CONTENT_TYPE)

    def __init__(self, path: str) -> None:
        self.path = Path(path)

    @classmethod
    def config_schema(cls) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to directory containing source files",
                },
            },
            "required": ["path"],
        }

    @classmethod
    def _fetch_single_file(cls, file_path: Path, project_id: str) -> Iterator[MaterialItem]:
        """Yield a single MaterialItem for a file (used by storage-based ingest)."""
        ext = file_path.suffix.lower()
        if ext not in cls.SUPPORTED_EXTENSIONS:
            return
        instance = cls(str(file_path.parent))
        try:
            text = instance._extract_text(file_path)
        except Exception as exc:
            print(f"WARNING: skipping {file_path.name} — {exc}", file=sys.stderr)
            return
        if not text or not text.strip():
            return
        raw_bytes = text.encode("utf-8") if isinstance(text, str) else text
        content_hash = hashlib.sha256(raw_bytes).hexdigest()
        source_path = str(file_path.resolve())
        yield MaterialItem(
            project_id=project_id,
            source_plugin=cls.plugin_name,
            source_path=source_path,
            content_hash=content_hash,
            url=file_path.as_uri(),
            work_title=file_path.stem,
            content=text,
            domain=Domain.TEXT,
            content_type=_EXT_TO_CONTENT_TYPE[ext],
        )

    def fetch(self, project_id: str) -> Iterator[MaterialItem]:
        all_files = sorted(
            p for p in self.path.rglob("*")
            if p.is_file() and p.suffix.lower() in self.SUPPORTED_EXTENSIONS
        )
        for file_path in all_files:
            ext = file_path.suffix.lower()
            try:
                text = self._extract_text(file_path)
            except Exception as exc:
                print(f"WARNING: skipping {file_path.name} — {exc}", file=sys.stderr)
                continue
            if not text or not text.strip():
                continue
            raw_bytes = text.encode("utf-8") if isinstance(text, str) else text
            content_hash = hashlib.sha256(raw_bytes).hexdigest()
            source_path = str(file_path.resolve())
            yield MaterialItem(
                project_id=project_id,
                source_plugin=self.plugin_name,
                source_path=source_path,
                content_hash=content_hash,
                url=file_path.as_uri(),
                work_title=file_path.stem,
                content=text,
                domain=Domain.TEXT,
                content_type=_EXT_TO_CONTENT_TYPE[ext],
            )

    def _extract_text(self, path: Path) -> str:
        ext = path.suffix.lower()
        if ext == ".txt":
            return path.read_text(encoding="utf-8", errors="replace")
        if ext == ".md":
            return path.read_text(encoding="utf-8", errors="replace")
        if ext in {".html", ".htm"}:
            return self._parse_html(path)
        if ext == ".epub":
            return self._parse_epub(path)
        if ext == ".pdf":
            return self._parse_pdf(path)
        raise ValueError(f"Unsupported extension: {ext}")

    @staticmethod
    def _parse_html(path: Path) -> str:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(path.read_bytes(), "html.parser")
        for tag in soup(["script", "style", "nav", "header", "footer"]):
            tag.decompose()
        return soup.get_text(separator="\n\n")

    @staticmethod
    def _parse_epub(path: Path) -> str:
        import ebooklib
        from bs4 import BeautifulSoup
        from ebooklib import epub

        book = epub.read_epub(str(path), options={"ignore_ncx": True})
        parts: list[str] = []
        for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            soup = BeautifulSoup(item.get_content(), "html.parser")
            text = soup.get_text(separator="\n\n")
            if text.strip():
                parts.append(text)
        return "\n\n".join(parts)

    @staticmethod
    def _parse_pdf(path: Path) -> str:
        from pypdf import PdfReader

        reader = PdfReader(str(path), strict=False)
        parts: list[str] = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                parts.append(text)
        return "\n\n".join(parts)
