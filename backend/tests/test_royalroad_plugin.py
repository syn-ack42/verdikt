"""Royal Road plugin tests.

Unit tests use canned HTML via MagicMock (no network).
Integration tests are marked @pytest.mark.infra and hit royalroad.com directly.
"""
import hashlib
import os
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from verdikt.plugins.royalroad import (
    LoginError,
    RoyalRoadPlugin,
    _fiction_id_from_url,
    _sample_paragraphs,
    _select_chapters,
)

# ---------------------------------------------------------------------------
# Canned HTML fixtures
# ---------------------------------------------------------------------------

LOGIN_PAGE_HTML = """
<html><body>
<form action="/account/login">
  <input name="__RequestVerificationToken" value="rr_csrf_xyz" />
</form>
</body></html>
"""

FICTION_PAGE_HTML = """
<html><body>
  <h1 class="font-white">A Great Adventure</h1>
  <h4 class="font-white"><a href="/profile/42/authorname">AuthorName</a></h4>
  <table id="chapters">
    <tbody>
      <tr>
        <td><a href="/fiction/11111/chapter/101/prologue">Prologue</a></td>
        <td><time datetime="2024-01-01T00:00:00.0000000+00:00">Jan 1, 2024</time></td>
      </tr>
      <tr>
        <td><a href="/fiction/11111/chapter/102/chapter-1">Chapter 1</a></td>
        <td><time datetime="2024-02-15T00:00:00.0000000+00:00">Feb 15, 2024</time></td>
      </tr>
      <tr>
        <td><a href="/fiction/11111/chapter/103/chapter-2">Chapter 2</a></td>
        <td><time datetime="2024-03-10T00:00:00.0000000+00:00">Mar 10, 2024</time></td>
      </tr>
    </tbody>
  </table>
</body></html>
"""

FICTION_PAGE_NO_CHAPTERS_HTML = """
<html><body>
  <h1 class="font-white">Empty Fiction</h1>
  <h4 class="font-white"><a href="/profile/1/author">Author</a></h4>
  <table id="chapters"><tbody></tbody></table>
</body></html>
"""

CHAPTER_HTML = """
<html><body>
  <div class="chapter-content">
    <p>The hero began their journey on a stormy night.</p>
    <p>The road was long and treacherous, winding through dark forests.</p>
    <p>At last, the destination came into view.</p>
  </div>
</body></html>
"""

CHAPTER_NO_CONTENT_HTML = """
<html><body><div class="main-content">No chapter content here.</div></body></html>
"""

BROWSE_PAGE_HTML = """
<html><body>
  <div class="row fiction-list-item">
    <div class="col-sm-10 search-content">
      <h2 class="fiction-title">
        <a class="font-red-sunglo bold" href="/fiction/11111/fiction-one">Fiction One</a>
      </h2>
    </div>
  </div>
  <div class="row fiction-list-item">
    <div class="col-sm-10 search-content">
      <h2 class="fiction-title">
        <a class="font-red-sunglo bold" href="/fiction/22222/fiction-two">Fiction Two</a>
      </h2>
    </div>
  </div>
  <div class="row fiction-list-item">
    <div class="col-sm-10 search-content">
      <h2 class="fiction-title">
        <a class="font-red-sunglo bold" href="/fiction/33333/fiction-three">Fiction Three</a>
      </h2>
    </div>
  </div>
</body></html>
"""

BROWSE_PAGE_EMPTY_HTML = "<html><body></body></html>"


def _resp(text: str, url: str = "https://www.royalroad.com/", status_code: int = 200) -> MagicMock:
    r = MagicMock()
    r.text = text
    r.url = url
    r.status_code = status_code
    r.ok = (status_code < 400)
    r.raise_for_status = MagicMock()
    return r


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def test_fiction_id_from_url_full_url():
    assert _fiction_id_from_url("https://www.royalroad.com/fiction/21220/mother-of-learning") == "21220"


def test_fiction_id_from_url_chapter_url():
    assert _fiction_id_from_url("https://www.royalroad.com/fiction/21220/chapter/301778/title") == "21220"


def test_fiction_id_from_url_no_match():
    assert _fiction_id_from_url("https://example.com/not/royalroad") is None


def test_fiction_id_from_url_path_only():
    assert _fiction_id_from_url("/fiction/99999/some-slug") == "99999"


# ---------------------------------------------------------------------------
# _select_chapters
# ---------------------------------------------------------------------------

def test_select_chapters_small_list_returned_whole():
    urls = ["a", "b"]
    assert _select_chapters(urls, "x", 0.3, 1.5) == urls


def test_select_chapters_single_chapter():
    urls = ["only"]
    assert _select_chapters(urls, "x", 0.3, 1.5) == urls


def test_select_chapters_correct_count():
    urls = [f"ch{i}" for i in range(100)]
    selected = _select_chapters(urls, "fiction123", 0.30, 1.5)
    assert len(selected) == 30


def test_select_chapters_order_preserved():
    """Selected chapters must appear in their original chronological order."""
    urls = [f"ch{i}" for i in range(50)]
    selected = _select_chapters(urls, "fiction123", 0.40, 1.5)
    indices = [urls.index(u) for u in selected]
    assert indices == sorted(indices)


def test_select_chapters_deterministic():
    urls = [f"ch{i}" for i in range(80)]
    a = _select_chapters(urls, "same_id", 0.25, 1.5)
    b = _select_chapters(urls, "same_id", 0.25, 1.5)
    assert a == b


def test_select_chapters_different_ids_differ():
    urls = [f"ch{i}" for i in range(80)]
    a = _select_chapters(urls, "id_alpha", 0.25, 1.5)
    b = _select_chapters(urls, "id_beta", 0.25, 1.5)
    assert a != b


def test_select_chapters_spans_full_range():
    """With low stddev we still expect the selection to include both early and late chapters."""
    urls = [f"ch{i}" for i in range(100)]
    selected = _select_chapters(urls, "fiction_x", 0.30, 1.5)
    indices = [int(u[2:]) for u in selected]
    assert min(indices) < 25
    assert max(indices) > 74


# ---------------------------------------------------------------------------
# _sample_paragraphs
# ---------------------------------------------------------------------------

def test_sample_paragraphs_small_text_returned_whole():
    text = "Para one.\n\nPara two."
    assert _sample_paragraphs(text, "fid", 0.5, 1.5) == text


def test_sample_paragraphs_correct_count():
    paras = [f"Paragraph {i}. " + ("word " * 10) for i in range(100)]
    text = "\n\n".join(paras)
    result = _sample_paragraphs(text, "fid", 0.20, 1.5)
    kept = [p for p in result.split("\n\n") if p.strip()]
    assert len(kept) == 20


def test_sample_paragraphs_deterministic():
    paras = [f"Para {i}. " + "x " * 5 for i in range(50)]
    text = "\n\n".join(paras)
    a = _sample_paragraphs(text, "same_id", 0.30, 1.5)
    b = _sample_paragraphs(text, "same_id", 0.30, 1.5)
    assert a == b


def test_sample_paragraphs_preserves_order():
    paras = [f"MARKER{i}" for i in range(40)]
    text = "\n\n".join(paras)
    result = _sample_paragraphs(text, "fid", 0.25, 1.5)
    markers = [p for p in result.split("\n\n") if p.startswith("MARKER")]
    nums = [int(m[6:]) for m in markers]
    assert nums == sorted(nums)


# ---------------------------------------------------------------------------
# Plugin class — basics
# ---------------------------------------------------------------------------

def test_plugin_name():
    assert RoyalRoadPlugin.plugin_name == "royalroad"


def test_supported_domains():
    from verdikt.core.models import Domain
    assert Domain.TEXT in RoyalRoadPlugin.supported_domains


def test_config_schema_structure():
    schema = RoyalRoadPlugin.config_schema()
    assert schema["type"] == "object"
    props = schema["properties"]
    assert "username" in props
    assert "password" in props
    assert props["password"]["format"] == "password"
    assert "fiction_urls" in props
    assert "search_urls" in props
    assert "include_following" in props
    assert schema["required"] == []


def test_help_markdown_non_empty():
    md = RoyalRoadPlugin.help_markdown()
    assert "royalroad.com" in md.lower()
    assert "VERDIKT_RR_CHAPTER_RATE" in md


# ---------------------------------------------------------------------------
# _login
# ---------------------------------------------------------------------------

def test_login_extracts_csrf_and_posts():
    plugin = RoyalRoadPlugin({"username": "user@example.com", "password": "secret"})
    with patch.object(plugin._session, "get", return_value=_resp(LOGIN_PAGE_HTML)) as mock_get, \
         patch.object(plugin._session, "post", return_value=_resp("", url="https://www.royalroad.com/")) as mock_post, \
         patch.object(plugin, "_delay"):
        plugin._login()

    mock_get.assert_called_once()
    assert mock_post.call_count == 1
    data = mock_post.call_args[1]["data"]
    assert data["__RequestVerificationToken"] == "rr_csrf_xyz"
    assert data["Email"] == "user@example.com"
    assert data["Password"] == "secret"
    assert plugin._logged_in


def test_login_idempotent():
    plugin = RoyalRoadPlugin({"username": "u@x.com", "password": "p"})
    plugin._logged_in = True
    with patch.object(plugin._session, "get") as mock_get:
        plugin._login()
    mock_get.assert_not_called()


def test_login_skips_when_no_credentials():
    plugin = RoyalRoadPlugin({})
    with patch.object(plugin._session, "get") as mock_get:
        plugin._login()
    mock_get.assert_not_called()
    assert not plugin._logged_in


def test_login_raises_on_redirect_back_to_login():
    plugin = RoyalRoadPlugin({"username": "u@x.com", "password": "wrong"})
    with patch.object(plugin._session, "get", return_value=_resp(LOGIN_PAGE_HTML)), \
         patch.object(plugin._session, "post", return_value=_resp("", url="https://www.royalroad.com/account/login")), \
         patch.object(plugin, "_delay"):
        with pytest.raises(LoginError, match="login failed"):
            plugin._login()


def test_login_raises_when_no_csrf_token():
    plugin = RoyalRoadPlugin({"username": "u@x.com", "password": "p"})
    with patch.object(plugin._session, "get", return_value=_resp("<html><body><form></form></body></html>")), \
         patch.object(plugin, "_delay"):
        with pytest.raises(LoginError, match="CSRF"):
            plugin._login()


# ---------------------------------------------------------------------------
# _get_fiction_page
# ---------------------------------------------------------------------------

def test_get_fiction_page_parses_title_and_author():
    plugin = RoyalRoadPlugin({})
    with patch.object(plugin._session, "get", return_value=_resp(FICTION_PAGE_HTML)):
        meta = plugin._get_fiction_page("11111")
    assert meta is not None
    assert meta["title"] == "A Great Adventure"
    assert meta["author"] == "AuthorName"


def test_get_fiction_page_parses_chapter_urls():
    plugin = RoyalRoadPlugin({})
    with patch.object(plugin._session, "get", return_value=_resp(FICTION_PAGE_HTML)):
        meta = plugin._get_fiction_page("11111")
    urls = meta["chapter_urls"]
    assert len(urls) == 3
    assert all("royalroad.com" in u for u in urls)
    assert "/chapter/101/" in urls[0]
    assert "/chapter/103/" in urls[2]


def test_get_fiction_page_chapter_order_preserved():
    plugin = RoyalRoadPlugin({})
    with patch.object(plugin._session, "get", return_value=_resp(FICTION_PAGE_HTML)):
        meta = plugin._get_fiction_page("11111")
    # Chapters must come back in table order (chronological)
    assert "/chapter/101/" in meta["chapter_urls"][0]
    assert "/chapter/102/" in meta["chapter_urls"][1]
    assert "/chapter/103/" in meta["chapter_urls"][2]


def test_get_fiction_page_last_updated_is_newest_chapter():
    plugin = RoyalRoadPlugin({})
    with patch.object(plugin._session, "get", return_value=_resp(FICTION_PAGE_HTML)):
        meta = plugin._get_fiction_page("11111")
    assert meta["last_updated"] is not None
    assert meta["last_updated"].year == 2024
    assert meta["last_updated"].month == 3


def test_get_fiction_page_404_returns_none():
    plugin = RoyalRoadPlugin({})
    with patch.object(plugin._session, "get", return_value=_resp("", status_code=404)):
        assert plugin._get_fiction_page("99999") is None


# ---------------------------------------------------------------------------
# _fetch_chapter_text
# ---------------------------------------------------------------------------

def test_fetch_chapter_text_extracts_content():
    plugin = RoyalRoadPlugin({})
    with patch.object(plugin._session, "get", return_value=_resp(CHAPTER_HTML)):
        text = plugin._fetch_chapter_text("https://www.royalroad.com/fiction/1/chapter/1/title")
    assert "hero began their journey" in text
    assert "long and treacherous" in text


def test_fetch_chapter_text_missing_div_returns_empty():
    plugin = RoyalRoadPlugin({})
    with patch.object(plugin._session, "get", return_value=_resp(CHAPTER_NO_CONTENT_HTML)):
        text = plugin._fetch_chapter_text("https://www.royalroad.com/fiction/1/chapter/1/title")
    assert text == ""


def test_fetch_chapter_text_http_error_returns_empty():
    plugin = RoyalRoadPlugin({})
    with patch.object(plugin._session, "get", return_value=_resp("", status_code=503)):
        text = plugin._fetch_chapter_text("https://www.royalroad.com/fiction/1/chapter/1/title")
    assert text == ""


# ---------------------------------------------------------------------------
# _fetch_fiction (two-stage sampling integration)
# ---------------------------------------------------------------------------

def _make_fetch_fiction_plugin(chapter_count: int = 10):
    """Return a plugin with mocked session for fiction + chapter pages."""
    plugin = RoyalRoadPlugin({})
    chapter_rows = "".join(
        f'<tr><td><a href="/fiction/11111/chapter/{100 + i}/ch-{i}">Ch {i}</a></td>'
        f'<td><time datetime="2024-01-{i+1:02d}T00:00:00.0000000+00:00">date</time></td></tr>'
        for i in range(chapter_count)
    )
    fiction_html = f"""
    <html><body>
      <h1 class="font-white">Test Fiction</h1>
      <h4 class="font-white"><a href="/profile/1/auth">TestAuthor</a></h4>
      <table id="chapters"><tbody>{chapter_rows}</tbody></table>
    </body></html>
    """

    call_n = {"n": 0}

    def fake_get(url, **kw):
        call_n["n"] += 1
        if "/fiction/11111" in url and "/chapter/" not in url:
            return _resp(fiction_html)
        return _resp(CHAPTER_HTML)

    plugin._session.get = MagicMock(side_effect=fake_get)
    return plugin, call_n


def test_fetch_fiction_returns_material_item():
    plugin, _ = _make_fetch_fiction_plugin(10)
    with patch.object(plugin, "_delay"):
        item = plugin._fetch_fiction("11111")
    assert item is not None
    assert item.work_title == "Test Fiction"
    assert item.author == "TestAuthor"
    assert item.source_path == "https://www.royalroad.com/fiction/11111"
    assert item.plugin_metadata["work_id"] == "11111"
    assert item.content_hash == hashlib.sha256(item.content.encode("utf-8")).hexdigest()


def test_fetch_fiction_two_stage_fetches_subset_of_chapters():
    """With 30 chapters and default 30% rate only ~9 chapter pages should be fetched."""
    plugin, call_n = _make_fetch_fiction_plugin(30)
    with patch.object(plugin, "_delay"):
        item = plugin._fetch_fiction("11111")
    assert item is not None
    # 1 fiction page + ~9 chapter pages (30 * 0.30 = 9); allow ±1 for rounding
    chapter_requests = call_n["n"] - 1
    assert 8 <= chapter_requests <= 10


def test_fetch_fiction_404_returns_none():
    plugin = RoyalRoadPlugin({})
    with patch.object(plugin._session, "get", return_value=_resp("", status_code=404)), \
         patch.object(plugin, "_delay"):
        assert plugin._fetch_fiction("99999") is None


def test_fetch_fiction_no_chapters_returns_none():
    plugin = RoyalRoadPlugin({})
    with patch.object(plugin._session, "get", return_value=_resp(FICTION_PAGE_NO_CHAPTERS_HTML)), \
         patch.object(plugin, "_delay"):
        assert plugin._fetch_fiction("11111") is None


def test_fetch_fiction_uses_passed_source_updated_at():
    plugin, _ = _make_fetch_fiction_plugin(5)
    fixed_date = datetime(2024, 6, 1, tzinfo=timezone.utc)
    with patch.object(plugin, "_delay"):
        item = plugin._fetch_fiction("11111", source_updated_at=fixed_date)
    assert item is not None
    assert item.plugin_metadata["source_updated_at"] == fixed_date.isoformat()


# ---------------------------------------------------------------------------
# _get_fiction_ids_from_browse
# ---------------------------------------------------------------------------

def test_browse_parses_fiction_ids():
    plugin = RoyalRoadPlugin({})
    responses = [_resp(BROWSE_PAGE_HTML), _resp(BROWSE_PAGE_EMPTY_HTML)]
    with patch.object(plugin._session, "get", side_effect=responses), \
         patch.object(plugin, "_delay"):
        ids = plugin._get_fiction_ids_from_browse("https://www.royalroad.com/fictions/best-rated", 10)
    assert ids == ["11111", "22222", "33333"]


def test_browse_respects_max_fictions():
    plugin = RoyalRoadPlugin({})
    with patch.object(plugin._session, "get", return_value=_resp(BROWSE_PAGE_HTML)), \
         patch.object(plugin, "_delay"):
        ids = plugin._get_fiction_ids_from_browse("https://www.royalroad.com/fictions/best-rated", 2)
    assert ids == ["11111", "22222"]


def test_browse_stops_on_empty_page():
    plugin = RoyalRoadPlugin({})
    responses = [_resp(BROWSE_PAGE_HTML), _resp(BROWSE_PAGE_EMPTY_HTML)]
    with patch.object(plugin._session, "get", side_effect=responses), \
         patch.object(plugin, "_delay"):
        ids = plugin._get_fiction_ids_from_browse("https://www.royalroad.com/fictions/best-rated", 100)
    # Only 3 items on first page, second page empty → stops
    assert len(ids) == 3


def test_browse_deduplicates_within_run():
    """Same fiction appearing on multiple pages is only collected once."""
    plugin = RoyalRoadPlugin({})
    # Two identical pages — fiction IDs would appear twice without dedup
    with patch.object(plugin._session, "get", side_effect=[_resp(BROWSE_PAGE_HTML), _resp(BROWSE_PAGE_HTML), _resp(BROWSE_PAGE_EMPTY_HTML)]), \
         patch.object(plugin, "_delay"):
        ids = plugin._get_fiction_ids_from_browse("https://www.royalroad.com/fictions/best-rated", 100)
    assert len(ids) == len(set(ids))


def test_browse_http_error_stops_gracefully():
    plugin = RoyalRoadPlugin({})
    with patch.object(plugin._session, "get", return_value=_resp("", status_code=503)), \
         patch.object(plugin, "_delay"):
        ids = plugin._get_fiction_ids_from_browse("https://www.royalroad.com/fictions/best-rated", 10)
    assert ids == []


# ---------------------------------------------------------------------------
# _normalise_search_entries
# ---------------------------------------------------------------------------

def test_normalise_search_entries_string_format():
    plugin = RoyalRoadPlugin({"search_urls": ["https://www.royalroad.com/fictions/best-rated"]})
    entries = plugin._normalise_search_entries()
    assert len(entries) == 1
    assert entries[0]["url"] == "https://www.royalroad.com/fictions/best-rated"
    assert entries[0]["max_fictions"] == 20  # default


def test_normalise_search_entries_object_format():
    plugin = RoyalRoadPlugin({"search_urls": [{"url": "https://www.royalroad.com/fictions/latest-updates", "max_fictions": 50}]})
    entries = plugin._normalise_search_entries()
    assert entries == [{"url": "https://www.royalroad.com/fictions/latest-updates", "max_fictions": 50}]


def test_normalise_search_entries_inherits_prev_max():
    plugin = RoyalRoadPlugin({"search_urls": [
        {"url": "https://rr.com/a", "max_fictions": 40},
        {"url": "https://rr.com/b"},  # no max_fictions → inherits 40
    ]})
    entries = plugin._normalise_search_entries()
    assert entries[1]["max_fictions"] == 40


def test_normalise_search_entries_caps_at_200():
    plugin = RoyalRoadPlugin({"search_urls": [{"url": "https://rr.com/a", "max_fictions": 9999}]})
    assert plugin._normalise_search_entries()[0]["max_fictions"] == 200


def test_normalise_search_entries_skips_empty():
    plugin = RoyalRoadPlugin({"search_urls": ["", {"url": ""}, "  "]})
    assert plugin._normalise_search_entries() == []


# ---------------------------------------------------------------------------
# estimate_count
# ---------------------------------------------------------------------------

def test_estimate_count_sums_search_and_fiction():
    plugin = RoyalRoadPlugin({
        "search_urls": [
            {"url": "https://rr.com/a", "max_fictions": 10},
            {"url": "https://rr.com/b", "max_fictions": 25},
        ],
        "fiction_urls": ["https://www.royalroad.com/fiction/1/x", "https://www.royalroad.com/fiction/2/y"],
    })
    assert plugin.estimate_count() == 37


def test_estimate_count_following_only_returns_none():
    """Cannot know the count of the following list without a network request."""
    plugin = RoyalRoadPlugin({"include_following": True})
    assert plugin.estimate_count() is None


def test_estimate_count_no_sources_returns_none():
    plugin = RoyalRoadPlugin({})
    assert plugin.estimate_count() is None


# ---------------------------------------------------------------------------
# get_updated_ats
# ---------------------------------------------------------------------------

def test_get_updated_ats_returns_dates():
    plugin = RoyalRoadPlugin({})
    with patch.object(plugin, "_get_fiction_page") as mock_page, \
         patch.object(plugin, "_delay"):
        mock_page.return_value = {
            "title": "T", "author": "A",
            "chapter_urls": [],
            "last_updated": datetime(2024, 3, 10, tzinfo=timezone.utc),
        }
        result = plugin.get_updated_ats(["11111", "22222"])

    assert result["11111"] == datetime(2024, 3, 10, tzinfo=timezone.utc)
    assert result["22222"] == datetime(2024, 3, 10, tzinfo=timezone.utc)
    assert mock_page.call_count == 2


def test_get_updated_ats_404_yields_none():
    plugin = RoyalRoadPlugin({})
    with patch.object(plugin, "_get_fiction_page", return_value=None), \
         patch.object(plugin, "_delay"):
        result = plugin.get_updated_ats(["99999"])
    assert result["99999"] is None


# ---------------------------------------------------------------------------
# fetch_by_ids
# ---------------------------------------------------------------------------

def test_fetch_by_ids_yields_items():
    plugin = RoyalRoadPlugin({})
    fake_item = MagicMock()
    fake_item.project_id = ""
    with patch.object(plugin, "_fetch_fiction", return_value=fake_item), \
         patch.object(plugin, "_delay"):
        items = list(plugin.fetch_by_ids("proj1", ["11111", "22222"]))
    assert len(items) == 2
    assert all(i.project_id == "proj1" for i in items)


def test_fetch_by_ids_skips_none():
    plugin = RoyalRoadPlugin({})
    with patch.object(plugin, "_fetch_fiction", return_value=None), \
         patch.object(plugin, "_delay"):
        items = list(plugin.fetch_by_ids("proj1", ["99999"]))
    assert items == []


def test_fetch_by_ids_passes_date_hints():
    plugin = RoyalRoadPlugin({})
    hint = datetime(2024, 1, 1, tzinfo=timezone.utc)
    captured = {}

    def fake_fetch(fid, source_updated_at=None):
        captured[fid] = source_updated_at
        return None

    with patch.object(plugin, "_fetch_fiction", side_effect=fake_fetch), \
         patch.object(plugin, "_delay"):
        list(plugin.fetch_by_ids("p", ["11111"], date_hints={"11111": hint}))

    assert captured["11111"] == hint


# ---------------------------------------------------------------------------
# fetch — integration of all sources
# ---------------------------------------------------------------------------

def test_fetch_deduplicates_ids():
    """Same fiction ID appearing in both browse and fiction_urls → fetched once."""
    plugin = RoyalRoadPlugin({
        "search_urls": [{"url": "https://rr.com/best", "max_fictions": 5}],
        "fiction_urls": ["https://www.royalroad.com/fiction/11111/fiction-one"],
    })
    fake_item = MagicMock()
    fake_item.project_id = ""

    with patch.object(plugin, "_get_fiction_ids_from_browse", return_value=["11111", "22222"]), \
         patch.object(plugin, "_fetch_fiction", return_value=fake_item), \
         patch.object(plugin, "_delay"):
        items = list(plugin.fetch("proj1"))

    fetched_ids = [plugin._fetch_fiction.call_args_list[i][0][0] for i in range(plugin._fetch_fiction.call_count)]
    assert fetched_ids.count("11111") == 1


def test_fetch_sets_project_id():
    plugin = RoyalRoadPlugin({"fiction_urls": ["https://www.royalroad.com/fiction/11111/x"]})
    fake_item = MagicMock()
    fake_item.project_id = ""

    with patch.object(plugin, "_fetch_fiction", return_value=fake_item), \
         patch.object(plugin, "_delay"):
        items = list(plugin.fetch("my_project"))

    assert all(i.project_id == "my_project" for i in items)


def test_fetch_skips_none_results():
    plugin = RoyalRoadPlugin({"fiction_urls": ["https://www.royalroad.com/fiction/11111/x"]})
    with patch.object(plugin, "_fetch_fiction", return_value=None), \
         patch.object(plugin, "_delay"):
        items = list(plugin.fetch("proj1"))
    assert items == []


def test_fetch_include_following_calls_get_following():
    plugin = RoyalRoadPlugin({"include_following": True})
    fake_item = MagicMock()
    fake_item.project_id = ""

    with patch.object(plugin, "_get_following_ids", return_value=["55555"]) as mock_follows, \
         patch.object(plugin, "_fetch_fiction", return_value=fake_item), \
         patch.object(plugin, "_delay"):
        items = list(plugin.fetch("proj1"))

    mock_follows.assert_called_once()
    assert len(items) == 1


def test_fetch_include_following_false_skips_following():
    plugin = RoyalRoadPlugin({"include_following": False})
    with patch.object(plugin, "_get_following_ids") as mock_follows, \
         patch.object(plugin, "_delay"):
        list(plugin.fetch("proj1"))
    mock_follows.assert_not_called()


# ---------------------------------------------------------------------------
# Integration tests — require network access (royalroad.com)
# ---------------------------------------------------------------------------

@pytest.mark.infra
def test_rr_browse_real():
    plugin = RoyalRoadPlugin({})
    ids = plugin._get_fiction_ids_from_browse(
        "https://www.royalroad.com/fictions/best-rated", max_fictions=5
    )
    assert len(ids) == 5
    assert all(id_.isdigit() for id_ in ids)


@pytest.mark.infra
def test_rr_fetch_fiction_real():
    """Fetch Mother of Learning (id=21220) — a stable, completed fiction."""
    plugin = RoyalRoadPlugin({})
    item = plugin._fetch_fiction("21220")
    assert item is not None
    assert "learning" in item.work_title.lower()
    assert len(item.content) > 100
    assert item.plugin_metadata["work_id"] == "21220"


@pytest.mark.infra
def test_rr_get_updated_ats_real():
    plugin = RoyalRoadPlugin({})
    result = plugin.get_updated_ats(["21220"])
    assert "21220" in result
    assert result["21220"] is not None


@pytest.mark.infra
def test_rr_login_real():
    username = os.environ.get("RR_USER")
    password = os.environ.get("RR_PASS")
    if not username or not password:
        pytest.skip("RR_USER / RR_PASS not set")
    plugin = RoyalRoadPlugin({"username": username, "password": password})
    plugin._login()
    assert plugin._logged_in
