"""AO3 content source plugin.

Fetches works from Archive of Our Own. Always retrieves the full work
(all chapters concatenated) via ?view_full_work=true, then retains only
a Gaussian-sampled subset of paragraphs to reduce storage.

Sampling:
  VERDIKT_AO3_SAMPLE_RATE   — fraction of paragraphs to keep (default 0.20, min 2 paragraphs)
  VERDIKT_AO3_SAMPLE_STDDEV — controls how tightly sampling is concentrated around the work's
                              midpoint. The value is the number of standard deviations that span
                              from the centre to the edge of the work; higher = broader spread,
                              lower = more tightly clustered in the middle. Default 1.5.
  The RNG is seeded from the work ID so repeated fetches of the same work yield identical samples.

Authentication:
  username / password are optional. Without them, only public works are accessible.

Rate limiting: AO3 is a community resource. This plugin enforces a minimum
3-second delay between requests and defaults to 5 seconds.
"""
from __future__ import annotations

import hashlib
import os
import re
import time
from collections.abc import Iterator
from datetime import datetime, timezone
from urllib.parse import urlparse, urlencode, parse_qs, urlunparse

from bs4 import BeautifulSoup, Comment

try:
    from curl_cffi import requests
    _IMPERSONATE = "chrome120"
except ImportError:
    import requests  # type: ignore[no-redef]
    _IMPERSONATE = None

import logging

from verdikt.core.models import ContentType, Domain, MaterialItem
from verdikt.plugins.base import PluginBase

log = logging.getLogger(__name__)

AO3_BASE = "https://archiveofourown.org"
_WORK_ID_RE = re.compile(r"/works/(\d+)")
_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
_UPDATED_AT_RE = re.compile(r"updated_at=(\d+)")
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36 "
    "Verdikt/0.3"
)

_ENV_SAMPLE_RATE = float(os.environ.get("VERDIKT_AO3_SAMPLE_RATE", "0.20"))
_ENV_SAMPLE_STDDEV = float(os.environ.get("VERDIKT_AO3_SAMPLE_STDDEV", "1.5"))


class LoginError(RuntimeError):
    pass


def _sample_paragraphs(text: str, work_id: str, sample_rate: float, stddev_span: float) -> str:
    """Return a deterministic Gaussian-sampled subset of paragraphs.

    Paragraphs are split by double-newline. Selection probability is proportional
    to a Gaussian centred at the midpoint of the work, with σ = n / (2 * stddev_span),
    so that ±stddev_span·σ reaches the edges of the work.

    The RNG is seeded from work_id so repeated fetches produce identical samples.
    """
    import numpy as np

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

    seed = int(hashlib.md5(work_id.encode()).hexdigest(), 16) % (2 ** 31)
    rng = np.random.default_rng(seed)
    chosen = np.sort(rng.choice(n, size=target, replace=False, p=probs))

    sampled = "\n\n".join(paragraphs[i] for i in chosen)
    log.debug(
        "ao3: work %s — sampled %d/%d paragraphs (rate=%.0f%%, stddev_span=%.1f)",
        work_id, target, n, sample_rate * 100, stddev_span,
    )
    return sampled


class AO3Plugin(PluginBase):
    plugin_name = "ao3"
    supported_domains = frozenset({Domain.TEXT})

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
        self._sample_rate = _ENV_SAMPLE_RATE
        self._sample_stddev = _ENV_SAMPLE_STDDEV

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
                    "description": "Optional. Required only to access locked or private works.",
                },
                "password": {
                    "type": "string",
                    "title": "AO3 Password",
                    "format": "password",
                    "description": "Optional. Required only to access locked or private works.",
                },
                "search_urls": {
                    "type": "array",
                    "title": "Search URLs",
                    "description": "Each search has its own limit. New rows default to the previous row's limit.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "url": {
                                "type": "string",
                                "format": "uri",
                                "title": "Search URL",
                            },
                            "max_works": {
                                "type": "integer",
                                "title": "Max",
                                "default": 20,
                                "minimum": 1,
                                "maximum": 500,
                            },
                        },
                    },
                    "default": [],
                },
                "work_urls": {
                    "type": "array",
                    "title": "Individual Work URLs",
                    "items": {"type": "string", "format": "uri"},
                    "default": [],
                    "description": "Direct links to individual works — always fetched, no limit",
                },
                "request_delay": {
                    "type": "number",
                    "title": "Delay between requests (s)",
                    "default": 5.0,
                    "minimum": 3.0,
                },
            },
            "required": [],
        }

    def _has_credentials(self) -> bool:
        return bool(self._config.get("username", "").strip() and self._config.get("password", "").strip())

    def _normalise_search_entries(self) -> list[dict]:
        """Return [{url, max_works}] normalised from both old string format and new object format."""
        default_max = min(int(self._config.get("max_works", 20)), 500)
        entries = []
        prev_max = default_max
        for item in self._config.get("search_urls", []):
            if isinstance(item, str):
                url = item.strip()
                if url:
                    entries.append({"url": url, "max_works": prev_max})
            elif isinstance(item, dict):
                url = str(item.get("url", "")).strip()
                if url:
                    mx = min(int(item.get("max_works", prev_max)), 500)
                    entries.append({"url": url, "max_works": mx})
                    prev_max = mx
        return entries

    def _delay(self) -> None:
        delay = max(3.0, float(self._config.get("request_delay", 5.0)))
        time.sleep(delay)

    @staticmethod
    def _is_login_redirect(resp) -> bool:
        return "/users/login" in str(resp.url)

    def _get(self, url: str, **kwargs):
        """GET with automatic session-expiry detection and one re-login retry."""
        resp = self._session.get(url, **kwargs)
        if self._is_login_redirect(resp) and self._logged_in:
            log.info("ao3: session expired (redirected to login), re-authenticating")
            self._logged_in = False
            self._login()
            resp = self._session.get(url, **kwargs)
        return resp

    def _login(self) -> None:
        if self._logged_in or not self._has_credentials():
            return

        log.info("ao3: GET %s", AO3_BASE)
        home = self._session.get(AO3_BASE, timeout=30)
        log.info("ao3: GET %s -> %s", AO3_BASE, home.status_code)
        home.raise_for_status()

        sign_in_url = f"{AO3_BASE}/users/login"
        log.info("ao3: GET %s", sign_in_url)
        resp = self._session.get(sign_in_url, timeout=30, headers={"Referer": AO3_BASE})
        log.info("ao3: GET %s -> %s", sign_in_url, resp.status_code)
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

        log.info("ao3: POST %s (login user=%r)", sign_in_url, self._config.get("username"))
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
        log.info("ao3: POST %s -> %s (final url: %s)", sign_in_url, login_resp.status_code, login_resp.url)
        if "/users/login" in login_resp.url:
            raise LoginError("AO3 login failed — check username and password")

        self._logged_in = True
        log.info("ao3: login successful for user %r", self._config.get("username"))

    @staticmethod
    def _parse_status_date(li_tag) -> datetime | None:
        for node in li_tag.find_all(string=lambda t: isinstance(t, Comment)):
            m = _UPDATED_AT_RE.search(node)
            if m:
                return datetime.fromtimestamp(int(m.group(1)), tz=timezone.utc)

        p = li_tag.find("p", class_="datetime")
        if p:
            try:
                return datetime.strptime(p.get_text(strip=True), "%d %b %Y").replace(tzinfo=timezone.utc)
            except ValueError:
                pass
        return None

    def _get_work_ids_from_search(self, url: str, max_works: int) -> dict[str, datetime | None]:
        results: dict[str, datetime | None] = {}
        page = 1
        parsed = urlparse(url)

        while len(results) < max_works:
            qs = parse_qs(parsed.query, keep_blank_values=True)
            qs["page"] = [str(page)]
            paged_url = urlunparse(parsed._replace(query=urlencode(qs, doseq=True)))

            log.info("ao3: GET %s", paged_url)
            resp = self._get(paged_url, timeout=30, headers={"Referer": AO3_BASE})
            log.info("ao3: GET %s -> %s", paged_url, resp.status_code)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            items = soup.find_all("li", id=re.compile(r"^work_\d+$"))
            log.debug("ao3: search page %d found %d work items", page, len(items))
            if items:
                log.debug("ao3: first <li> snippet: %s", str(items[0])[:400])
            if not items:
                break

            for li in items:
                m = re.match(r"^work_(\d+)$", li.get("id", ""))
                if m:
                    wid = m.group(1)
                    date = self._parse_status_date(li)
                    if date is None:
                        comments = [str(c) for c in li.find_all(string=lambda t: isinstance(t, Comment))]
                        datetime_p = li.find("p", class_="datetime")
                        log.debug(
                            "ao3: no date for work_%s — comments=%r datetime_p=%r li_tail=%s",
                            wid, comments, str(datetime_p) if datetime_p else None, str(li)[-300:],
                        )
                    else:
                        log.debug("ao3: search work_id=%s date=%s", wid, date)
                    results[wid] = date
                    if len(results) >= max_works:
                        break

            next_btn = soup.find("a", rel="next")
            if not next_btn:
                break

            page += 1
            self._delay()

        return results

    @staticmethod
    def _extract_date_from_soup(soup) -> datetime | None:
        dd = soup.find("dd", class_="status") or soup.find("dd", class_="published")
        if dd:
            m = _DATE_RE.search(dd.get_text())
            if m:
                try:
                    return datetime.strptime(m.group(1), "%Y-%m-%d").replace(tzinfo=timezone.utc)
                except ValueError:
                    pass
        return None

    def _get_work_updated_at(self, work_id: str) -> datetime | None:
        url = f"{AO3_BASE}/works/{work_id}?view_adult=true"
        log.info("ao3: GET %s", url)
        resp = self._get(url, timeout=30, headers={"Referer": AO3_BASE})
        log.info("ao3: GET %s -> %s", url, resp.status_code)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return self._extract_date_from_soup(BeautifulSoup(resp.text, "html.parser"))

    def _extract_work_id(self, url: str) -> str | None:
        m = _WORK_ID_RE.search(url)
        return m.group(1) if m else None

    def _fetch_work(self, work_id: str, source_updated_at: datetime | None = None) -> MaterialItem | None:
        url = f"{AO3_BASE}/works/{work_id}?view_full_work=true&view_adult=true"
        log.info("ao3: GET %s", url)
        resp = self._get(url, timeout=60, headers={"Referer": AO3_BASE})
        log.info("ao3: GET %s -> %s", url, resp.status_code)
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
        full_content = "\n\n".join(content_parts)

        if not full_content.strip():
            log.warning("ao3: work %s had no extractable content", work_id)
            return None

        # Sample a Gaussian-distributed subset of paragraphs to reduce storage.
        content = _sample_paragraphs(full_content, work_id, self._sample_rate, self._sample_stddev)

        if source_updated_at is None:
            source_updated_at = self._extract_date_from_soup(soup)

        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        canonical_url = f"{AO3_BASE}/works/{work_id}"

        plugin_metadata: dict = {"work_id": work_id}
        if source_updated_at is not None:
            plugin_metadata["source_updated_at"] = source_updated_at.isoformat()

        return MaterialItem(
            project_id="",
            source_plugin="ao3",
            source_path=canonical_url,
            url=canonical_url,
            work_title=title,
            author=author,
            content=content,
            content_hash=content_hash,
            plugin_metadata=plugin_metadata,
            domain=Domain.TEXT,
            content_type=ContentType.PLAIN,
        )

    def estimate_count(self) -> int | None:
        entries = self._normalise_search_entries()
        work_count = sum(1 for wu in self._config.get("work_urls", []) if str(wu).strip())
        return sum(e["max_works"] for e in entries) + work_count

    def get_updated_ats(self, work_ids: list[str]) -> dict[str, datetime | None]:
        """Check last-modified dates for stored works without downloading full content."""
        self._login()

        found: dict[str, datetime | None] = {}

        for entry in self._normalise_search_entries():
            page_results = self._get_work_ids_from_search(entry["url"], entry["max_works"])
            found.update(page_results)
            self._delay()

        search_found = set(found.keys())
        overlap = [wid for wid in work_ids if wid in search_found and found.get(wid) is not None]
        log.debug(
            "ao3: get_updated_ats — checking %d stored works; search returned %d IDs; "
            "%d overlap with stored (have date); stored IDs: %s; search IDs sample: %s",
            len(work_ids), len(search_found), len(overlap),
            work_ids[:10], list(search_found)[:10],
        )

        remaining = [wid for wid in work_ids if found.get(wid) is None]
        log.debug("ao3: %d works not covered by search, will fetch individually", len(remaining))
        for wid in remaining:
            found[wid] = self._get_work_updated_at(wid)
            self._delay()

        return {wid: found.get(wid) for wid in work_ids}

    def fetch_by_ids(
        self,
        project_id: str,
        work_ids: list[str],
        date_hints: dict[str, datetime | None] | None = None,
    ) -> Iterator[MaterialItem]:
        self._login()
        log.info("ao3: fetching %d works for project %s", len(work_ids), project_id)
        for wid in work_ids:
            log.debug("ao3: fetching work %s", wid)
            hint = date_hints.get(wid) if date_hints else None
            item = self._fetch_work(wid, source_updated_at=hint)
            if item is not None:
                item.project_id = project_id
                yield item
            self._delay()

    def fetch(self, project_id: str) -> Iterator[MaterialItem]:
        self._login()

        search_dates: dict[str, datetime | None] = {}
        for entry in self._normalise_search_entries():
            results = self._get_work_ids_from_search(entry["url"], entry["max_works"])
            search_dates.update(results)
            self._delay()

        extra_ids: list[str] = []
        for wu in self._config.get("work_urls", []):
            wid = self._extract_work_id(str(wu))
            if wid and wid not in search_dates:
                extra_ids.append(wid)

        seen: set[str] = set()
        for wid in list(search_dates.keys()) + extra_ids:
            if wid in seen:
                continue
            seen.add(wid)
            item = self._fetch_work(wid, source_updated_at=search_dates.get(wid))
            if item is not None:
                item.project_id = project_id
                yield item
            self._delay()
