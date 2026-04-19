"""AO3 content source plugin.

Fetches works from Archive of Our Own. Always retrieves the full work
(all chapters concatenated) via ?view_full_work=true.

Rate limiting: AO3 is a community resource. This plugin enforces a minimum
3-second delay between requests and defaults to 5 seconds.
"""
from __future__ import annotations

import hashlib
import re
import time
from collections.abc import Iterator
from urllib.parse import urlparse, urlencode, parse_qs, urlunparse

from bs4 import BeautifulSoup

try:
    from curl_cffi import requests
    _IMPERSONATE = "chrome120"
except ImportError:
    import requests  # type: ignore[no-redef]
    _IMPERSONATE = None

from verdikt.core.models import ContentType, Domain, MaterialItem
from verdikt.plugins.base import PluginBase

AO3_BASE = "https://archiveofourown.org"
_WORK_ID_RE = re.compile(r"/works/(\d+)")
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36 "
    "Verdikt/0.3"
)


class LoginError(RuntimeError):
    pass


class AO3Plugin(PluginBase):
    plugin_name = "ao3"

    def __init__(self, config: dict) -> None:
        self._config = config
        if _IMPERSONATE:
            self._session = requests.Session(impersonate=_IMPERSONATE)
        else:
            self._session = requests.Session()
            self._session.headers.update({
                "User-Agent": _USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
            })
        self._logged_in = False

    @classmethod
    def config_schema(cls) -> dict:
        return {
            "type": "object",
            "title": "AO3 Plugin",
            "description": "Fetch works from Archive of Our Own",
            "properties": {
                "username": {
                    "type": "string",
                    "title": "AO3 Username",
                },
                "password": {
                    "type": "string",
                    "title": "AO3 Password",
                    "format": "password",
                },
                "search_url": {
                    "type": "string",
                    "title": "Search URL",
                    "format": "uri",
                    "description": "Full AO3 search URL (paste from browser address bar)",
                },
                "work_urls": {
                    "type": "array",
                    "title": "Individual Work URLs",
                    "items": {"type": "string", "format": "uri"},
                    "default": [],
                    "description": "Direct links to individual AO3 works",
                },
                "max_works": {
                    "type": "integer",
                    "title": "Max works",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 100,
                },
                "request_delay": {
                    "type": "number",
                    "title": "Delay between requests (s)",
                    "default": 5.0,
                    "minimum": 3.0,
                },
            },
            "required": ["username", "password"],
        }

    def _delay(self) -> None:
        delay = max(3.0, float(self._config.get("request_delay", 5.0)))
        time.sleep(delay)

    def _login(self) -> None:
        if self._logged_in:
            return

        # Visit homepage first to pick up session cookies before the login form.
        home = self._session.get(AO3_BASE, timeout=30)
        home.raise_for_status()
        self._delay()

        sign_in_url = f"{AO3_BASE}/users/login"
        resp = self._session.get(
            sign_in_url,
            timeout=30,
            headers={"Referer": AO3_BASE},
        )
        if resp.status_code == 404:
            raise LoginError(
                "AO3 sign-in page returned 404. The login URL may have changed or "
                "AO3 is blocking automated access. Check https://archiveofourown.org/users/login "
                "in a browser to confirm the URL is correct."
            )
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")
        token_input = soup.find("input", {"name": "authenticity_token"})
        if token_input is None:
            raise LoginError(
                "Could not find authenticity_token on the AO3 sign-in page. "
                "AO3 may have changed their login form structure."
            )
        token = token_input["value"]

        self._delay()
        login_resp = self._session.post(
            sign_in_url,
            data={
                "user[login]": self._config["username"],
                "user[password]": self._config["password"],
                "authenticity_token": token,
                "commit": "Log in",
            },
            timeout=30,
            allow_redirects=True,
            headers={"Referer": sign_in_url},
        )
        if "/users/login" in login_resp.url:
            raise LoginError("AO3 login failed — check username and password")

        self._logged_in = True

    def _get_work_ids_from_search(self, url: str, max_works: int) -> list[str]:
        work_ids: list[str] = []
        page = 1
        parsed = urlparse(url)

        while len(work_ids) < max_works:
            qs = parse_qs(parsed.query, keep_blank_values=True)
            qs["page"] = [str(page)]
            paged_url = urlunparse(parsed._replace(query=urlencode(qs, doseq=True)))

            resp = self._session.get(paged_url, timeout=30, headers={"Referer": AO3_BASE})
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            items = soup.find_all("li", id=re.compile(r"^work_\d+$"))
            if not items:
                break

            for li in items:
                m = re.match(r"^work_(\d+)$", li.get("id", ""))
                if m:
                    work_ids.append(m.group(1))
                    if len(work_ids) >= max_works:
                        break

            next_btn = soup.find("a", rel="next")
            if not next_btn:
                break

            page += 1
            self._delay()

        return work_ids

    def _extract_work_id(self, url: str) -> str | None:
        m = _WORK_ID_RE.search(url)
        return m.group(1) if m else None

    def _fetch_work(self, work_id: str) -> MaterialItem | None:
        url = f"{AO3_BASE}/works/{work_id}?view_full_work=true&view_adult=true"
        resp = self._session.get(url, timeout=60, headers={"Referer": AO3_BASE})
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        title_tag = soup.find("h2", class_="title")
        title = title_tag.get_text(strip=True) if title_tag else f"Work {work_id}"

        author_tag = soup.find("a", rel="author")
        author = author_tag.get_text(strip=True) if author_tag else "Anonymous"

        chapters = soup.find_all("div", class_="userstuff")
        content_parts: list[str] = []
        for ch in chapters:
            for tag in ch.find_all(["h3", "h4"]):
                tag.decompose()
            content_parts.append(ch.get_text(separator="\n", strip=True))
        content = "\n\n".join(content_parts)

        if not content.strip():
            return None

        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        canonical_url = f"{AO3_BASE}/works/{work_id}"

        return MaterialItem(
            project_id="",  # caller fills this in
            source_plugin="ao3",
            source_path=canonical_url,
            url=canonical_url,
            work_id=work_id,
            work_title=title,
            author=author,
            content=content,
            content_hash=content_hash,
            domain=Domain.TEXT,
            content_type=ContentType.PLAIN,
        )

    def fetch(self, project_id: str) -> Iterator[MaterialItem]:
        self._login()

        max_works: int = min(int(self._config.get("max_works", 20)), 100)
        work_ids: list[str] = []

        search_url = self._config.get("search_url", "").strip()
        if search_url:
            work_ids.extend(self._get_work_ids_from_search(search_url, max_works))

        for wu in self._config.get("work_urls", []):
            wid = self._extract_work_id(wu)
            if wid and wid not in work_ids:
                work_ids.append(wid)

        seen: set[str] = set()
        for wid in work_ids[:max_works]:
            if wid in seen:
                continue
            seen.add(wid)

            item = self._fetch_work(wid)
            if item is not None:
                item.project_id = project_id
                yield item
            self._delay()
