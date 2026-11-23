"""Runs inside Composio's sandbox: fetch each cited page and look for its quotes.

Reads [[url, [quote, ...]], ...] as JSON on stdin and prints one {"code": n, "found": [bool, ...]}
per page, in the same order. Results are matched by position, because the sandbox redacts
anything that looks like a secret, such as an address ending in "create-auth-token".

It must stand alone, so Check repeats the page rules in research/links.py (Page.normalise and
Page.readable); a test keeps the two in step.
"""

import html
import http.client
import json
import re
import sys
import unicodedata
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Tuple, Union

Answer = Dict[str, Union[int, List[bool]]]


class Check:
    USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko)"
    TIMEOUT_SECONDS = 20
    MAX_BYTES = 5000000
    WORKERS = 8

    @staticmethod
    def normalise(text: str) -> str:
        text = unicodedata.normalize("NFKC", html.unescape(text))
        text = text.translate(str.maketrans("‘’“”–—", "''\"\"--"))
        return re.sub(r"\s+", " ", text).strip().lower()

    @staticmethod
    def readable(page: str) -> str:
        page = re.sub(r"(?is)<(script|style|noscript)\b.*?</\1>", " ", page)
        return re.sub(r"<[^>]+>", " ", page)

    @classmethod
    def page(cls, item: Tuple[str, List[str]]) -> Answer:
        url, quotes = item
        try:
            request = urllib.request.Request(url, headers={"User-Agent": cls.USER_AGENT})
            with urllib.request.urlopen(request, timeout=cls.TIMEOUT_SECONDS) as response:
                code, body = response.status, response.read(cls.MAX_BYTES)
        except urllib.error.HTTPError as err:
            return {"code": err.code, "found": [False] * len(quotes)}
        except (OSError, http.client.HTTPException, ValueError):
            return {"code": 0, "found": [False] * len(quotes)}
        text = cls.normalise(cls.readable(body.decode("utf-8", "replace")))
        return {"code": code, "found": [cls.normalise(quote) in text for quote in quotes]}

    @classmethod
    def run(cls, items: List[Tuple[str, List[str]]]) -> List[Answer]:
        with ThreadPoolExecutor(max_workers=cls.WORKERS) as pool:
            return list(pool.map(cls.page, items))


if __name__ == "__main__":
    print(json.dumps(Check.run(json.load(sys.stdin))))
