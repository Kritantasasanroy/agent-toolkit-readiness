"""Checks that each evidence page loads and still contains the quoted text."""

import html
import http.client
import json
import re
import unicodedata
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Tuple

from research.profile import Evidence, Profile


class PageStatus(Enum):
    LIVE = "live"
    NOT_FOUND = "not_found"
    REFUSED = "refused"
    SERVER_ERROR = "server_error"
    UNREACHABLE = "unreachable"

    @classmethod
    def for_code(cls, code: int) -> "PageStatus":
        if code in (404, 410):
            return cls.NOT_FOUND
        return cls.SERVER_ERROR if code >= 500 else cls.REFUSED


class QuoteStatus(Enum):
    FOUND = "found"
    MISSING = "missing"
    UNCHECKED = "unchecked"


@dataclass(frozen=True)
class Page:
    # Some docs sites refuse requests that do not look like a browser.
    USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko)"
    TIMEOUT_SECONDS = 20
    MAX_BYTES = 5_000_000
    WORKERS = 16

    url: str
    status: PageStatus
    http_code: int
    text: str
    truncated: bool = False

    @staticmethod
    def normalise(text: str) -> str:
        """Lower-case, unescape and collapse spacing and typographic marks so a quote can match."""
        text = unicodedata.normalize("NFKC", html.unescape(text))
        text = text.translate(str.maketrans("\u2018\u2019\u201c\u201d\u2013\u2014", "''\"\"--"))
        return re.sub(r"\s+", " ", text).strip().lower()

    @staticmethod
    def readable(page: str) -> str:
        page = re.sub(r"(?is)<(script|style|noscript)\b.*?</\1>", " ", page)
        return re.sub(r"<[^>]+>", " ", page)

    @classmethod
    def fetch(cls, url: str) -> "Page":
        try:
            request = urllib.request.Request(url, headers={"User-Agent": cls.USER_AGENT})
            with urllib.request.urlopen(request, timeout=cls.TIMEOUT_SECONDS) as response:
                raw = response.read(cls.MAX_BYTES + 1)
                code = response.status
        except urllib.error.HTTPError as err:
            return cls(url, PageStatus.for_code(err.code), err.code, "")
        except (OSError, http.client.HTTPException, ValueError):
            # A dead host or an address urllib cannot send is a finding about the
            # evidence, not a failure of the run. UnicodeError is a ValueError.
            return cls(url, PageStatus.UNREACHABLE, 0, "")
        body = raw[:cls.MAX_BYTES].decode("utf-8", errors="replace")
        return cls(url, PageStatus.LIVE, code, cls.normalise(cls.readable(body)), truncated=len(raw) > cls.MAX_BYTES)

    def quote_status(self, quote: str) -> QuoteStatus:
        if self.status is not PageStatus.LIVE:
            return QuoteStatus.UNCHECKED
        if self.normalise(quote) in self.text:
            return QuoteStatus.FOUND
        # A quote beyond the size cap may exist; only a complete page can prove it absent.
        return QuoteStatus.UNCHECKED if self.truncated else QuoteStatus.MISSING


@dataclass(frozen=True)
class LinkCheck:
    app_id: int
    app: str
    field: str
    url: str
    page: PageStatus
    http_code: int
    quote: QuoteStatus

    @classmethod
    def from_json(cls, doc: Mapping[str, object]) -> "LinkCheck":
        return cls(
            app_id=int(str(doc["app_id"])),
            app=str(doc["app"]),
            field=str(doc["field"]),
            url=str(doc["url"]),
            page=PageStatus(doc["page"]),
            http_code=int(str(doc["http_code"])),
            quote=QuoteStatus(doc["quote"]),
        )

    def to_json(self) -> Dict[str, object]:
        return {
            "app_id": self.app_id,
            "app": self.app,
            "field": self.field,
            "url": self.url,
            "page": self.page.value,
            "http_code": self.http_code,
            "quote": self.quote.value,
        }

    @property
    def is_verified(self) -> bool:
        return self.page is PageStatus.LIVE and self.quote is QuoteStatus.FOUND


@dataclass(frozen=True)
class LinkReport:
    checks: Tuple[LinkCheck, ...]

    @classmethod
    def run(cls, profiles: Iterable[Profile]) -> "LinkReport":
        """Fetch each distinct evidence URL once and test every quote cited from it."""
        cited: List[Tuple[Profile, Evidence]] = [(p, e) for p in profiles for e in p.evidence]
        urls = sorted({e.url for _, e in cited})
        with ThreadPoolExecutor(max_workers=Page.WORKERS) as pool:
            pages = dict(zip(urls, pool.map(Page.fetch, urls)))
        return cls(tuple(
            LinkCheck(
                app_id=p.app_id,
                app=p.app,
                field=e.field.value,
                url=e.url,
                page=pages[e.url].status,
                http_code=pages[e.url].http_code,
                quote=pages[e.url].quote_status(e.quote),
            )
            for p, e in cited
        ))

    @classmethod
    def read(cls, path: Path) -> "LinkReport":
        return cls(tuple(LinkCheck.from_json(doc) for doc in json.loads(path.read_text())))

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps([c.to_json() for c in self.checks], indent=1))

    def totals(self) -> Dict[str, object]:
        return {
            "citations": len(self.checks),
            "pages": dict(Counter(c.page.value for c in self.checks)),
            "quotes": dict(Counter(c.quote.value for c in self.checks)),
            "verified": sum(c.is_verified for c in self.checks),
        }
