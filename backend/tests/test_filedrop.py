from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from verdikt.core.models import ContentType
from verdikt.plugins.filedrop import FileDropPlugin


def test_fetch_txt_file(tmp_path):
    (tmp_path / "book.txt").write_text("Hello world.\n\nSecond paragraph.", encoding="utf-8")
    items = list(FileDropPlugin(str(tmp_path)).fetch("proj1"))
    assert len(items) == 1
    assert items[0].content_type == ContentType.PLAIN.value
    assert "Hello world" in items[0].content


def test_fetch_md_file(tmp_path):
    (tmp_path / "notes.md").write_text("# Title\n\nSome content.", encoding="utf-8")
    items = list(FileDropPlugin(str(tmp_path)).fetch("proj1"))
    assert len(items) == 1
    assert items[0].content_type == ContentType.MARKDOWN.value


def test_fetch_html_file(tmp_path):
    html = "<html><body><script>alert(1)</script><p>Real content.</p></body></html>"
    (tmp_path / "page.html").write_text(html, encoding="utf-8")
    items = list(FileDropPlugin(str(tmp_path)).fetch("proj1"))
    assert len(items) == 1
    assert "Real content" in items[0].content
    assert "alert" not in items[0].content


def test_fetch_skips_unsupported_extension(tmp_path):
    (tmp_path / "data.csv").write_text("a,b,c", encoding="utf-8")
    (tmp_path / "book.txt").write_text("Some text content.", encoding="utf-8")
    items = list(FileDropPlugin(str(tmp_path)).fetch("proj1"))
    assert len(items) == 1


def test_fetch_skips_empty_file(tmp_path):
    (tmp_path / "empty.txt").write_text("", encoding="utf-8")
    items = list(FileDropPlugin(str(tmp_path)).fetch("proj1"))
    assert len(items) == 0


def test_fetch_skips_whitespace_only_file(tmp_path):
    (tmp_path / "blank.txt").write_text("   \n  ", encoding="utf-8")
    items = list(FileDropPlugin(str(tmp_path)).fetch("proj1"))
    assert len(items) == 0


def test_work_title_is_stem(tmp_path):
    (tmp_path / "my_book.txt").write_text("Content here.", encoding="utf-8")
    items = list(FileDropPlugin(str(tmp_path)).fetch("proj1"))
    assert items[0].work_title == "my_book"


def test_url_is_file_uri(tmp_path):
    (tmp_path / "doc.txt").write_text("Hello.", encoding="utf-8")
    items = list(FileDropPlugin(str(tmp_path)).fetch("proj1"))
    assert items[0].url.startswith("file://")


def test_multiple_files_sorted(tmp_path):
    (tmp_path / "b_file.txt").write_text("B content.", encoding="utf-8")
    (tmp_path / "a_file.txt").write_text("A content.", encoding="utf-8")
    items = list(FileDropPlugin(str(tmp_path)).fetch("proj1"))
    assert items[0].work_title == "a_file"
    assert items[1].work_title == "b_file"


def test_project_id_set_on_items(tmp_path):
    (tmp_path / "book.txt").write_text("Some text.", encoding="utf-8")
    items = list(FileDropPlugin(str(tmp_path)).fetch("my_project"))
    assert items[0].project_id == "my_project"


def test_source_plugin_is_filedrop(tmp_path):
    (tmp_path / "book.txt").write_text("Some text.", encoding="utf-8")
    items = list(FileDropPlugin(str(tmp_path)).fetch("proj1"))
    assert items[0].source_plugin == "filedrop"


def test_fetch_pdf_via_mock(tmp_path):
    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")

    mock_page = MagicMock()
    mock_page.extract_text.return_value = "PDF page text content."
    mock_reader = MagicMock()
    mock_reader.pages = [mock_page]

    with patch("verdikt.plugins.filedrop.FileDropPlugin._parse_pdf", return_value="PDF page text content."):
        items = list(FileDropPlugin(str(tmp_path)).fetch("proj1"))

    assert len(items) == 1
    assert items[0].content_type == ContentType.PDF.value
    assert "PDF page text" in items[0].content


def test_recursive_traversal(tmp_path):
    subdir = tmp_path / "sub"
    subdir.mkdir()
    (subdir / "nested.txt").write_text("Nested content here.", encoding="utf-8")
    (tmp_path / "top.txt").write_text("Top level content.", encoding="utf-8")
    items = list(FileDropPlugin(str(tmp_path)).fetch("proj1"))
    assert len(items) == 2


def test_source_path_is_absolute(tmp_path):
    (tmp_path / "book.txt").write_text("Some content.", encoding="utf-8")
    items = list(FileDropPlugin(str(tmp_path)).fetch("proj1"))
    from pathlib import Path as _Path
    assert _Path(items[0].source_path).is_absolute()


def test_content_hash_is_sha256(tmp_path):
    (tmp_path / "book.txt").write_text("Some content.", encoding="utf-8")
    items = list(FileDropPlugin(str(tmp_path)).fetch("proj1"))
    assert items[0].content_hash is not None
    assert len(items[0].content_hash) == 64


def test_parse_error_skipped_with_warning(tmp_path, capsys):
    (tmp_path / "bad.pdf").write_bytes(b"not a pdf at all")
    (tmp_path / "good.txt").write_text("Good content.", encoding="utf-8")
    with patch("verdikt.plugins.filedrop.FileDropPlugin._parse_pdf", side_effect=ValueError("corrupt")):
        items = list(FileDropPlugin(str(tmp_path)).fetch("proj1"))
    assert len(items) == 1
    assert "WARNING" in capsys.readouterr().err


def test_fetch_epub_via_mock(tmp_path):
    epub_path = tmp_path / "book.epub"
    epub_path.write_bytes(b"PK fake epub")

    with patch("verdikt.plugins.filedrop.FileDropPlugin._parse_epub", return_value="Chapter one text content."):
        items = list(FileDropPlugin(str(tmp_path)).fetch("proj1"))

    assert len(items) == 1
    assert items[0].content_type == ContentType.EPUB.value
    assert "Chapter one" in items[0].content
