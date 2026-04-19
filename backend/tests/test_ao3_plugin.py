"""AO3 plugin tests.

Unit tests use canned HTML via responses mock library (no network).
Integration tests are marked @pytest.mark.infra and require AO3 credentials
in environment variables AO3_USER and AO3_PASS.
"""
import os
import hashlib
from unittest.mock import MagicMock, patch

import pytest

from verdikt.plugins.ao3 import AO3Plugin, LoginError


# ---------------------------------------------------------------------------
# Canned HTML helpers
# ---------------------------------------------------------------------------

SIGN_IN_HTML = """
<html><body>
<form action="/users/sign_in">
  <input name="authenticity_token" value="test_token_abc123" />
</form>
</body></html>
"""

SEARCH_PAGE_HTML = """
<html><body>
  <ol class="work index group">
    <li id="work_12345"><a href="/works/12345">Work One</a></li>
    <li id="work_67890"><a href="/works/67890">Work Two</a></li>
    <li id="work_11111"><a href="/works/11111">Work Three</a></li>
  </ol>
</body></html>
"""

SEARCH_PAGE_EMPTY_HTML = """
<html><body>
  <ol class="work index group"></ol>
</body></html>
"""

WORK_HTML = """
<html><body>
  <h2 class="title heading">A Fine Story</h2>
  <a rel="author" href="/users/authorname">AuthorName</a>
  <div id="chapters">
    <div class="userstuff">
      <p>Chapter one content here. It is quite interesting.</p>
    </div>
    <div class="userstuff">
      <p>Chapter two content here. Even more interesting.</p>
    </div>
  </div>
</body></html>
"""


def _make_response(text, url="https://archiveofourown.org/final", status_code=200):
    r = MagicMock()
    r.text = text
    r.url = url
    r.status_code = status_code
    r.raise_for_status = MagicMock()
    return r


# ---------------------------------------------------------------------------
# Unit tests (no network)
# ---------------------------------------------------------------------------

def test_config_schema():
    schema = AO3Plugin.config_schema()
    assert schema["type"] == "object"
    assert "username" in schema["properties"]
    assert "password" in schema["properties"]
    assert schema["properties"]["password"]["format"] == "password"
    assert "username" in schema["required"]
    assert "password" in schema["required"]


def test_plugin_name():
    assert AO3Plugin.plugin_name == "ao3"


def test_login_extracts_token_and_posts():
    plugin = AO3Plugin({"username": "u", "password": "p"})

    with patch.object(plugin._session, "get", return_value=_make_response(SIGN_IN_HTML)) as mock_get, \
         patch.object(plugin._session, "post", return_value=_make_response("", url="https://archiveofourown.org/users/u")) as mock_post, \
         patch.object(plugin, "_delay"):
        plugin._login()

    mock_get.assert_called_once()
    call_data = mock_post.call_args[1]["data"]
    assert call_data["authenticity_token"] == "test_token_abc123"
    assert call_data["user[login]"] == "u"
    assert call_data["user[password]"] == "p"
    assert plugin._logged_in


def test_login_raises_on_redirect_back_to_sign_in():
    plugin = AO3Plugin({"username": "u", "password": "wrong"})
    with patch.object(plugin._session, "get", return_value=_make_response(SIGN_IN_HTML)), \
         patch.object(plugin._session, "post", return_value=_make_response("", url="https://archiveofourown.org/users/sign_in")), \
         patch.object(plugin, "_delay"):
        with pytest.raises(LoginError):
            plugin._login()


def test_login_raises_when_no_token():
    plugin = AO3Plugin({"username": "u", "password": "p"})
    with patch.object(plugin._session, "get", return_value=_make_response("<html><body></body></html>")), \
         patch.object(plugin, "_delay"):
        with pytest.raises(LoginError):
            plugin._login()


def test_get_work_ids_from_search():
    plugin = AO3Plugin({"username": "u", "password": "p"})
    responses = [
        _make_response(SEARCH_PAGE_HTML),
        _make_response(SEARCH_PAGE_EMPTY_HTML),
    ]
    with patch.object(plugin._session, "get", side_effect=responses), \
         patch.object(plugin, "_delay"):
        ids = plugin._get_work_ids_from_search("https://archiveofourown.org/works/search?query=test", 10)
    assert ids == ["12345", "67890", "11111"]


def test_get_work_ids_respects_max_works():
    plugin = AO3Plugin({"username": "u", "password": "p"})
    with patch.object(plugin._session, "get", return_value=_make_response(SEARCH_PAGE_HTML)), \
         patch.object(plugin, "_delay"):
        ids = plugin._get_work_ids_from_search("https://archiveofourown.org/works/search?query=test", 2)
    assert ids == ["12345", "67890"]


def test_fetch_work_parses_content():
    plugin = AO3Plugin({"username": "u", "password": "p"})
    with patch.object(plugin._session, "get", return_value=_make_response(WORK_HTML)):
        item = plugin._fetch_work("12345")

    assert item is not None
    assert item.work_title == "A Fine Story"
    assert item.author == "AuthorName"
    assert "Chapter one content here" in item.content
    assert "Chapter two content here" in item.content
    assert item.source_path == "https://archiveofourown.org/works/12345"
    assert item.work_id == "12345"
    assert item.content_hash == hashlib.sha256(item.content.encode("utf-8")).hexdigest()


def test_fetch_work_returns_none_on_404():
    plugin = AO3Plugin({"username": "u", "password": "p"})
    resp = _make_response("", status_code=404)
    resp.raise_for_status = MagicMock()
    with patch.object(plugin._session, "get", return_value=resp):
        result = plugin._fetch_work("99999")
    assert result is None


def test_extract_work_id():
    plugin = AO3Plugin({"username": "u", "password": "p"})
    assert plugin._extract_work_id("https://archiveofourown.org/works/12345") == "12345"
    assert plugin._extract_work_id("https://archiveofourown.org/works/12345/chapters/67890") == "12345"
    assert plugin._extract_work_id("https://example.com/not/ao3") is None


def test_fetch_deduplicates_work_ids():
    plugin = AO3Plugin({
        "username": "u", "password": "p",
        "search_url": "https://archiveofourown.org/works/search?q=test",
        "work_urls": ["https://archiveofourown.org/works/12345"],
        "max_works": 10,
    })

    def fake_get(url, **kwargs):
        if "sign_in" in url:
            return _make_response(SIGN_IN_HTML)
        if "search" in url:
            return _make_response(SEARCH_PAGE_HTML)
        return _make_response(WORK_HTML)

    def fake_post(*args, **kwargs):
        return _make_response("", url="https://archiveofourown.org/users/u")

    with patch.object(plugin._session, "get", side_effect=fake_get), \
         patch.object(plugin._session, "post", side_effect=fake_post), \
         patch.object(plugin, "_delay"):
        items = list(plugin.fetch("proj1"))

    # work 12345 appears in both search results and work_urls → deduplicated
    work_ids = [i.work_id for i in items]
    assert work_ids.count("12345") == 1
    assert len(set(work_ids)) == len(work_ids)


def test_fetch_sets_project_id():
    plugin = AO3Plugin({
        "username": "u", "password": "p",
        "work_urls": ["https://archiveofourown.org/works/12345"],
        "max_works": 1,
    })

    def fake_get(url, **kwargs):
        if "sign_in" in url:
            return _make_response(SIGN_IN_HTML)
        return _make_response(WORK_HTML)

    def fake_post(*args, **kwargs):
        return _make_response("", url="https://archiveofourown.org/users/u")

    with patch.object(plugin._session, "get", side_effect=fake_get), \
         patch.object(plugin._session, "post", side_effect=fake_post), \
         patch.object(plugin, "_delay"):
        items = list(plugin.fetch("my_project"))

    assert all(i.project_id == "my_project" for i in items)


# ---------------------------------------------------------------------------
# Integration tests — require real AO3 credentials and network access
# ---------------------------------------------------------------------------

@pytest.mark.infra
def test_ao3_login_real():
    username = os.environ.get("AO3_USER")
    password = os.environ.get("AO3_PASS")
    if not username or not password:
        pytest.skip("AO3_USER / AO3_PASS not set")
    plugin = AO3Plugin({"username": username, "password": password})
    plugin._login()
    assert plugin._logged_in


@pytest.mark.infra
def test_ao3_fetch_real_work():
    username = os.environ.get("AO3_USER")
    password = os.environ.get("AO3_PASS")
    if not username or not password:
        pytest.skip("AO3_USER / AO3_PASS not set")
    plugin = AO3Plugin({"username": username, "password": password})
    plugin._login()
    plugin._delay()
    item = plugin._fetch_work("1")  # First AO3 work ever posted
    if item is not None:
        assert len(item.content) > 0
        assert item.work_id == "1"
