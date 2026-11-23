"""Runs inside Composio's sandbox: fetch each cited page and look for its quotes.

Reads [[url, [quote, ...]], ...] as JSON on stdin and prints one {"code": n, "found": [bool, ...]}
per page, in the same order. Results are matched by position, because the sandbox redacts
anything that looks like a secret, such as an address ending in "create-auth-token".
It must stand alone, so it repeats the page rules in research/links.py (Page.normalise and
Page.readable); a test keeps the two in step.
"""

import html
import http.client
import json
import re
import sys
import unicodedata
import urllib.request
from concurrent.futures import ThreadPoolExecutor

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko)"


def normalise(text):
    text = unicodedata.normalize("NFKC", html.unescape(text))
    text = text.translate(str.maketrans("‘’“”–—", "''\"\"--"))
    return re.sub(r"\s+", " ", text).strip().lower()


def readable(page):
    page = re.sub(r"(?is)<(script|style|noscript)\b.*?</\1>", " ", page)
    return re.sub(r"<[^>]+>", " ", page)


def check(item):
    url, quotes = item
    try:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=20) as response:
            code, body = response.status, response.read(5_000_000)
    except urllib.error.HTTPError as err:
        return {"code": err.code, "found": [False] * len(quotes)}
    except (OSError, http.client.HTTPException, ValueError):
        return {"code": 0, "found": [False] * len(quotes)}
    text = normalise(readable(body.decode("utf-8", "replace")))
    return {"code": code, "found": [normalise(q) in text for q in quotes]}


if __name__ == "__main__":
    with ThreadPoolExecutor(max_workers=8) as pool:
        print(json.dumps(list(pool.map(check, json.load(sys.stdin)))))
