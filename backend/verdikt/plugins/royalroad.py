"""Royal Road content source plugin.

Fetches web fictions from Royal Road. Uses a two-stage Gaussian sampling
strategy to avoid downloading every chapter of long serials:

  Stage 1 — chapter selection:
    A Gaussian curve over the chapter list selects a subset of chapters to
    actually fetch. This centres sampling around the work's midpoint so all
    parts of the story are represented, while avoiding requests for every chapter.

  Stage 2 — paragraph sampling:
    From the concatenated text of the fetched chapters, a second Gaussian curve
    picks a subset of paragraphs, following the same logic as the AO3 plugin.

Both curves are seeded from the fiction ID, so repeated fetches of the same
work produce identical samples.

Environment variables:
  VERDIKT_RR_REQUEST_DELAY    — seconds between requests (default 2.0, min 1.0)
  VERDIKT_RR_CHAPTER_RATE     — fraction of chapters to fetch (default 0.30)
  VERDIKT_RR_CHAPTER_STDDEV   — Gaussian spread for chapter selection; higher =
                                 broader coverage, lower = more centred (default 1.5)
  VERDIKT_RR_SAMPLE_RATE      — fraction of paragraphs to keep (default 0.20)
  VERDIKT_RR_SAMPLE_STDDEV    — Gaussian spread for paragraph sampling (default 1.5)
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import time
from collections.abc import Iterator
from datetime import datetime
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import numpy as np
import requests
from bs4 import BeautifulSoup

from verdikt.core.models import ContentType, Domain, MaterialItem
from verdikt.plugins.base import PluginBase

log = logging.getLogger(__name__)

_RR_BASE = "https://www.royalroad.com"
_FICTION_ID_RE = re.compile(r"/fiction/(\d+)")
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36 "
    "Verdikt/0.3"
)

_ENV_REQUEST_DELAY = max(1.0, float(os.environ.get("VERDIKT_RR_REQUEST_DELAY", "2.0")))
_ENV_CHAPTER_RATE = float(os.environ.get("VERDIKT_RR_CHAPTER_RATE", "0.30"))
_ENV_CHAPTER_STDDEV = float(os.environ.get("VERDIKT_RR_CHAPTER_STDDEV", "1.5"))
_ENV_SAMPLE_RATE = float(os.environ.get("VERDIKT_RR_SAMPLE_RATE", "0.20"))
_ENV_SAMPLE_STDDEV = float(os.environ.get("VERDIKT_RR_SAMPLE_STDDEV", "1.5"))


class LoginError(RuntimeError):
    pass


def _fiction_id_from_url(url: str) -> str | None:
    m = _FICTION_ID_RE.search(url)
    return m.group(1) if m else None


def _select_chapters(
    chapter_urls: list[str],
    fiction_id: str,
    chapter_rate: float,
    stddev_span: float,
) -> list[str]:
    """Stage 1: Gaussian-weighted selection of which chapters to fetch.

    Chapters are weighted by a normal distribution centred at the midpoint of
    the chapter list, so the selection spans the whole work rather than
    clustering at the start.
    """
    n = len(chapter_urls)
    min_chapters = min(2, n)
    target = max(min_chapters, int(round(n * chapter_rate)))
    if target >= n or n <= 2:
        return chapter_urls

    center = (n - 1) / 2.0
    sigma = max(n / (2.0 * stddev_span), 1e-6)
    raw_w = np.array([np.exp(-0.5 * ((i - center) / sigma) ** 2) for i in range(n)])
    probs = raw_w / raw_w.sum()

    seed = int(hashlib.md5(f"ch:{fiction_id}".encode()).hexdigest(), 16) % (2**31)
    rng = np.random.default_rng(seed)
    chosen = np.sort(rng.choice(n, size=target, replace=False, p=probs))

    log.debug(
        "rr: fiction %s — selected %d/%d chapters (rate=%.0f%%, stddev=%.1f)",
        fiction_id, target, n, chapter_rate * 100, stddev_span,
    )
    return [chapter_urls[i] for i in chosen]


def _sample_paragraphs(text: str, fiction_id: str, sample_rate: float, stddev_span: float) -> str:
    """Stage 2: Gaussian-weighted selection of paragraphs within the fetched chapters.

    Mirrors the AO3 plugin's sampling logic exactly.
    """
    paragraphs = [p for p in text.split("\n\n") if p.strip()]
    n = len(paragraphs)
    min_keep = 2
    target = max(min_keep, int(round(n * sample_rate)))
    if target >= n or n <= min_keep:
        return text

    center = (n - 1) / 2.0
    sigma = max(n / (2.0 * stddev_span), 1e-6)
    raw_w = np.array([np.exp(-0.5 * ((i - center) / sigma) ** 2) for i in range(n)])
    probs = raw_w / raw_w.sum()

    seed = int(hashlib.md5(f"para:{fiction_id}".encode()).hexdigest(), 16) % (2**31)
    rng = np.random.default_rng(seed)
    chosen = np.sort(rng.choice(n, size=target, replace=False, p=probs))

    log.debug(
        "rr: fiction %s — sampled %d/%d paragraphs (rate=%.0f%%, stddev=%.1f)",
        fiction_id, target, n, sample_rate * 100, stddev_span,
    )
    return "\n\n".join(paragraphs[i] for i in chosen)


class RoyalRoadPlugin(PluginBase):
    plugin_name = "royalroad"
    supported_domains = frozenset({Domain.TEXT})

    def __init__(self, config: dict) -> None:
        self._config = config
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": _USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            # No Accept-Encoding: let requests negotiate gzip/deflate only.
            # Explicitly advertising "br" causes Royal Road to send Brotli,
            # which requests cannot decode without the brotli package.
        })
        self._logged_in = False
        self._chapter_rate = _ENV_CHAPTER_RATE
        self._chapter_stddev = _ENV_CHAPTER_STDDEV
        self._sample_rate = _ENV_SAMPLE_RATE
        self._sample_stddev = _ENV_SAMPLE_STDDEV

    @classmethod
    def config_schema(cls) -> dict:
        return {
            "type": "object",
            "title": "Royal Road Plugin",
            "description": "Fetch web fictions from Royal Road",
            "properties": {
                "username": {
                    "type": "string",
                    "title": "Royal Road Email",
                    "description": "Optional. Required only to import your followed fictions.",
                },
                "password": {
                    "type": "string",
                    "title": "Royal Road Password",
                    "format": "password",
                    "description": "Optional. Required only to import your followed fictions.",
                },
                "fiction_urls": {
                    "type": "array",
                    "title": "Fiction URLs",
                    "description": "Direct links to specific Royal Road fictions — always fetched.",
                    "items": {"type": "string", "format": "uri"},
                    "default": [],
                },
                "search_urls": {
                    "type": "array",
                    "title": "Search / Browse URLs",
                    "description": (
                        "Paste any Royal Road search or browse page URL "
                        "(e.g. royalroad.com/fictions/best-rated or a search result URL). "
                        "Each entry has its own limit."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "url": {
                                "type": "string",
                                "format": "uri",
                                "title": "Browse / Search URL",
                            },
                            "max_fictions": {
                                "type": "integer",
                                "title": "Max",
                                "default": 20,
                                "minimum": 1,
                                "maximum": 200,
                            },
                        },
                    },
                    "default": [],
                },
                "include_following": {
                    "type": "boolean",
                    "title": "Import followed fictions",
                    "description": "Import all fictions from your Royal Road following list (requires login).",
                    "default": False,
                },
            },
            "required": [],
        }

    @classmethod
    def help_markdown(cls) -> str:
        return """\
## Royal Road Plugin

Fetches web fictions from [royalroad.com](https://www.royalroad.com).

### Adding fictions

**Individual fictions** — paste the URL of any fiction page, e.g.:
`https://www.royalroad.com/fiction/21220/mother-of-learning`

**Browse / search results** — paste any Royal Road browse or search URL, e.g.:
`https://www.royalroad.com/fictions/best-rated?genre=portal-fantasy&page=1`
Set a *Max* limit per URL to control how many fictions are imported.

**Following list** — enable *Import followed fictions* and supply your email and
password to import all fictions you follow on Royal Road.

### Sampling

To avoid fetching hundreds of chapters per novel, the plugin selects a
representative subset of chapters using a Gaussian curve centred at the
work's midpoint, then samples paragraphs within those chapters using a
second Gaussian curve. The selection is deterministic — the same fiction
always produces the same sample.

Adjust the sampling fractions via environment variables:
- `VERDIKT_RR_CHAPTER_RATE` (default 0.30 — 30% of chapters fetched)
- `VERDIKT_RR_SAMPLE_RATE` (default 0.20 — 20% of paragraphs kept)

### Rate limiting

A 2-second delay is applied between every request. Override with
`VERDIKT_RR_REQUEST_DELAY`. Royal Road does not publish official rate
limits; be considerate and avoid running many concurrent ingest jobs.
"""

    # ── internal helpers ────────────────────────────────────────────────

    def _delay(self) -> None:
        time.sleep(_ENV_REQUEST_DELAY)

    def _has_credentials(self) -> bool:
        return bool(
            self._config.get("username", "").strip()
            and self._config.get("password", "").strip()
        )

    def _login(self) -> None:
        if self._logged_in or not self._has_credentials():
            return

        login_url = f"{_RR_BASE}/account/login"
        log.info("rr: GET %s (login page)", login_url)
        resp = self._session.get(login_url, timeout=30)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")
        token_input = soup.find("input", {"name": "__RequestVerificationToken"})
        if token_input is None:
            raise LoginError(
                "Could not find CSRF token on Royal Road login page. "
                "The login form may have changed — please report this."
            )
        token = token_input.get("value", "")

        log.info("rr: POST %s (login)", login_url)
        login_resp = self._session.post(
            login_url,
            data={
                "Email": self._config["username"].strip(),
                "Password": self._config["password"],
                "__RequestVerificationToken": token,
                "RememberMe": "false",
            },
            timeout=30,
            allow_redirects=True,
        )

        if "/account/login" in login_resp.url:
            raise LoginError(
                "Royal Road login failed — check your email address and password."
            )

        self._logged_in = True
        log.info("rr: login successful")

    def _get_fiction_page(self, fiction_id: str) -> dict | None:
        """Fetch the fiction landing page and parse metadata + chapter list.

        Returns dict with: title, author, chapter_urls (list[str]), last_updated (datetime|None).
        Returns None if the fiction is not found (404).
        """
        url = f"{_RR_BASE}/fiction/{fiction_id}"
        log.debug("rr: GET fiction page %s", fiction_id)
        resp = self._session.get(url, timeout=30)
        if resp.status_code == 404:
            log.warning("rr: fiction %s not found (404)", fiction_id)
            return None
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        # Title
        title_tag = soup.find("h1", class_="font-white") or soup.find("h1")
        title = title_tag.get_text(strip=True) if title_tag else f"Fiction {fiction_id}"

        # Author — "by Author Name" header block
        author = "Unknown"
        author_h4 = soup.find("h4", class_="font-white")
        if author_h4:
            a_tag = author_h4.find("a")
            author = (a_tag or author_h4).get_text(strip=True)

        # Chapter list from the data table
        chapter_urls: list[str] = []
        last_updated: datetime | None = None
        for row in soup.select("table#chapters tbody tr"):
            ch_link = row.select_one("td a[href*='/chapter/']")
            if ch_link and ch_link.get("href"):
                href = ch_link["href"]
                chapter_urls.append(href if href.startswith("http") else _RR_BASE + href)
            time_tag = row.select_one("td time[datetime]")
            if time_tag and time_tag.get("datetime"):
                try:
                    dt_str = time_tag["datetime"]
                    last_updated = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
                except (ValueError, TypeError):
                    pass

        log.debug(
            "rr: fiction %s — title=%r, chapters=%d, last_updated=%s",
            fiction_id, title, len(chapter_urls), last_updated,
        )
        return {
            "title": title,
            "author": author,
            "chapter_urls": chapter_urls,
            "last_updated": last_updated,
        }

    def _fetch_chapter_text(self, url: str) -> str:
        """Fetch a single chapter page and return its plain text."""
        log.debug("rr: GET chapter %s", url)
        resp = self._session.get(url, timeout=30)
        if not resp.ok:
            log.warning("rr: chapter %s returned %s — skipping", url, resp.status_code)
            return ""
        soup = BeautifulSoup(resp.text, "html.parser")
        content_div = soup.select_one("div.chapter-content")
        if not content_div:
            log.warning("rr: no div.chapter-content at %s", url)
            return ""
        for tag in content_div.find_all(["script", "style"]):
            tag.decompose()
        return content_div.get_text(separator="\n", strip=True)

    def _fetch_fiction(
        self,
        fiction_id: str,
        source_updated_at: datetime | None = None,
    ) -> MaterialItem | None:
        """Fetch a complete fiction using two-stage Gaussian sampling."""
        meta = self._get_fiction_page(fiction_id)
        if meta is None:
            return None
        self._delay()

        chapter_urls = meta["chapter_urls"]
        if not chapter_urls:
            log.warning("rr: fiction %s has no chapters listed", fiction_id)
            return None

        # Stage 1: select which chapters to fetch
        selected = _select_chapters(
            chapter_urls, fiction_id, self._chapter_rate, self._chapter_stddev
        )

        # Fetch the selected chapters
        content_parts: list[str] = []
        for i, ch_url in enumerate(selected):
            text = self._fetch_chapter_text(ch_url)
            if text:
                content_parts.append(text)
            if i < len(selected) - 1:
                self._delay()

        full_content = "\n\n".join(content_parts)
        if not full_content.strip():
            log.warning("rr: fiction %s produced no extractable text", fiction_id)
            return None

        # Stage 2: sample paragraphs within the fetched chapters
        content = _sample_paragraphs(
            full_content, fiction_id, self._sample_rate, self._sample_stddev
        )

        if source_updated_at is None:
            source_updated_at = meta["last_updated"]

        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        canonical_url = f"{_RR_BASE}/fiction/{fiction_id}"

        plugin_metadata: dict = {"work_id": fiction_id}
        if source_updated_at is not None:
            plugin_metadata["source_updated_at"] = source_updated_at.isoformat()

        return MaterialItem(
            project_id="",
            source_plugin="royalroad",
            source_path=canonical_url,
            url=canonical_url,
            work_title=meta["title"],
            author=meta["author"],
            content=content,
            content_hash=content_hash,
            plugin_metadata=plugin_metadata,
            domain=Domain.TEXT,
            content_type=ContentType.PLAIN,
        )

    def _get_fiction_ids_from_browse(self, url: str, max_fictions: int) -> list[str]:
        """Paginate a Royal Road browse/search URL and return fiction IDs."""
        ids: list[str] = []
        seen: set[str] = set()
        page = 1
        parsed = urlparse(url)

        while len(ids) < max_fictions:
            qs = parse_qs(parsed.query, keep_blank_values=True)
            qs["page"] = [str(page)]
            paged_url = urlunparse(parsed._replace(query=urlencode(qs, doseq=True)))

            log.debug("rr: GET browse page %d: %s", page, paged_url)
            resp = self._session.get(paged_url, timeout=30)
            if not resp.ok:
                log.warning("rr: browse page %d returned %s", page, resp.status_code)
                break

            soup = BeautifulSoup(resp.text, "html.parser")
            links = soup.select("div.fiction-list-item h2.fiction-title a")
            if not links:
                break

            for a_tag in links:
                fid = _fiction_id_from_url(a_tag.get("href", ""))
                if fid and fid not in seen:
                    seen.add(fid)
                    ids.append(fid)
                    if len(ids) >= max_fictions:
                        break

            page += 1
            self._delay()

        log.debug("rr: browse collected %d fiction IDs", len(ids))
        return ids[:max_fictions]

    def _get_following_ids(self) -> list[str]:
        """Return fiction IDs from the user's Royal Road following list (requires login)."""
        self._login()
        follows_url = f"{_RR_BASE}/my/follows"
        log.info("rr: GET following list")
        resp = self._session.get(follows_url, timeout=30)
        if not resp.ok:
            log.warning("rr: could not fetch following list: %s", resp.status_code)
            return []
        soup = BeautifulSoup(resp.text, "html.parser")
        ids: list[str] = []
        seen: set[str] = set()
        for a_tag in soup.select("div.fiction-list-item h2.fiction-title a"):
            fid = _fiction_id_from_url(a_tag.get("href", ""))
            if fid and fid not in seen:
                seen.add(fid)
                ids.append(fid)
        log.debug("rr: following list returned %d fictions", len(ids))
        return ids

    def _normalise_search_entries(self) -> list[dict]:
        """Return [{url, max_fictions}] normalised from config."""
        prev_max = 20
        entries = []
        for item in self._config.get("search_urls", []):
            if isinstance(item, str):
                url = item.strip()
                if url:
                    entries.append({"url": url, "max_fictions": prev_max})
            elif isinstance(item, dict):
                url = str(item.get("url", "")).strip()
                if url:
                    mx = min(int(item.get("max_fictions", prev_max)), 200)
                    entries.append({"url": url, "max_fictions": mx})
                    prev_max = mx
        return entries

    # ── PluginBase interface ─────────────────────────────────────────────

    def estimate_count(self) -> int | None:
        entries = self._normalise_search_entries()
        fiction_count = sum(
            1 for u in self._config.get("fiction_urls", []) if str(u).strip()
        )
        total = sum(e["max_fictions"] for e in entries) + fiction_count
        if total == 0:
            # Following-list count is unknown without a network request.
            return None
        return total

    def get_updated_ats(self, work_ids: list[str]) -> dict[str, datetime | None]:
        """Check last-updated dates without re-fetching chapters.

        One fiction page load per work — cheap compared to re-fetching content.
        """
        result: dict[str, datetime | None] = {}
        for fiction_id in work_ids:
            meta = self._get_fiction_page(fiction_id)
            result[fiction_id] = meta["last_updated"] if meta else None
            self._delay()
        return result

    def fetch_by_ids(
        self,
        project_id: str,
        work_ids: list[str],
        **kwargs,
    ) -> Iterator[MaterialItem]:
        date_hints: dict[str, datetime | None] = kwargs.get("date_hints") or {}
        log.info("rr: fetching %d fictions for project %s", len(work_ids), project_id)
        for fiction_id in work_ids:
            hint = date_hints.get(fiction_id)
            item = self._fetch_fiction(fiction_id, source_updated_at=hint)
            if item is not None:
                item.project_id = project_id
                yield item
            self._delay()

    def fetch(self, project_id: str) -> Iterator[MaterialItem]:
        collected_ids: list[str] = []
        seen: set[str] = set()

        # Following list (requires login)
        if self._config.get("include_following"):
            for fid in self._get_following_ids():
                if fid not in seen:
                    seen.add(fid)
                    collected_ids.append(fid)
            self._delay()

        # Browse / search URLs
        for entry in self._normalise_search_entries():
            for fid in self._get_fiction_ids_from_browse(entry["url"], entry["max_fictions"]):
                if fid not in seen:
                    seen.add(fid)
                    collected_ids.append(fid)

        # Explicit fiction URLs
        for raw_url in self._config.get("fiction_urls", []):
            fid = _fiction_id_from_url(str(raw_url))
            if fid and fid not in seen:
                seen.add(fid)
                collected_ids.append(fid)

        log.info("rr: fetching %d unique fictions for project %s", len(collected_ids), project_id)
        for fiction_id in collected_ids:
            item = self._fetch_fiction(fiction_id)
            if item is not None:
                item.project_id = project_id
                yield item
            self._delay()
