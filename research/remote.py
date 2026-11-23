"""The evidence check run a second time from Composio's sandbox.

A Composio tool-router session gives a remote shell. The same quote check that runs on this
machine (research/links.py) runs there too, from a different network, so a page that blocks
one vantage point or serves it different content shows up as a disagreement.
"""

import base64
import json
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Tuple

from research.composio import CatalogError
from research.links import LinkReport, QuoteStatus
from research.profile import Profile


@dataclass(frozen=True)
class PageAnswer:
    """What the sandbox saw for one page: the HTTP code (0 if unreachable) and which quotes it found."""

    code: int
    found: Tuple[bool, ...]

    @classmethod
    def from_json(cls, doc: Mapping[str, object]) -> "PageAnswer":
        found = doc["found"]
        if not isinstance(found, list):
            raise CatalogError(f"the sandbox sent {doc!r}")
        return cls(int(str(doc["code"])), tuple(bool(hit) for hit in found))


@dataclass(frozen=True)
class Sandbox:
    API = "https://backend.composio.dev/api/v3/tool_router/session"
    TIMEOUT_SECONDS = 300
    SCRIPT = Path(__file__).with_name("remote_check.py")

    api_key: str
    session_id: str

    @classmethod
    def open(cls, api_key: str, user_id: str = "research") -> "Sandbox":
        if not api_key:
            raise CatalogError("set COMPOSIO_API_KEY to use the Composio sandbox")
        reply = cls._post(api_key, cls.API, {"user_id": user_id})
        return cls(api_key, str(reply["session_id"]))

    @staticmethod
    def _post(api_key: str, url: str, body: Mapping[str, object]) -> Mapping[str, object]:
        request = urllib.request.Request(
            url, data=json.dumps(body).encode(), headers={"x-api-key": api_key, "content-type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=Sandbox.TIMEOUT_SECONDS) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as err:
            raise CatalogError(f"Composio returned HTTP {err.code}") from err
        except (OSError, ValueError) as err:
            raise CatalogError(f"could not reach Composio: {err}") from err

    def bash(self, command: str) -> str:
        reply = self._post(self.api_key, f"{self.API}/{self.session_id}/execute",
                           {"tool_slug": "COMPOSIO_REMOTE_BASH_TOOL", "arguments": {"command": command}})
        if reply.get("error"):
            raise CatalogError(f"sandbox command failed: {reply['error']}")
        data = reply.get("data")
        if not isinstance(data, dict) or "stdout" not in data:
            raise CatalogError(f"the sandbox sent no output: {reply!r}")
        return str(data["stdout"])

    def check_pages(self, pages: List[Tuple[str, List[str]]]) -> List[PageAnswer]:
        """Run remote_check.py in the sandbox on one batch of (url, quotes); results keep the order."""
        script = base64.b64encode(self.SCRIPT.read_bytes()).decode()
        payload = base64.b64encode(json.dumps(pages).encode()).decode()
        out = self.bash(f"echo {script} | base64 -d > /tmp/rc.py && echo {payload} | base64 -d | python3 /tmp/rc.py")
        try:
            return [PageAnswer.from_json(doc) for doc in json.loads(out)]
        except (ValueError, KeyError, TypeError) as err:
            raise CatalogError(f"could not read the sandbox's answer: {err}") from err


@dataclass(frozen=True)
class RemoteCheck:
    app_id: int
    url: str
    quote: str
    code: int
    found: bool

    def to_json(self) -> Dict[str, object]:
        return {"app_id": self.app_id, "url": self.url, "quote": self.quote, "code": self.code, "found": self.found}


@dataclass(frozen=True)
class RemoteReport:
    BATCH = 25
    PARALLEL = 6

    checks: Tuple[RemoteCheck, ...]

    @classmethod
    def run(cls, profiles: Iterable[Profile], sandbox: Sandbox) -> "RemoteReport":
        cited = [(p.app_id, e.url, e.quote) for p in profiles for e in p.evidence]
        answers = cls._ask(sandbox, cited)
        seen: Dict[str, int] = {}
        checks = []
        for app_id, url, quote in cited:
            index = seen.get(url, 0)
            seen[url] = index + 1
            answer = answers[url]
            checks.append(RemoteCheck(app_id, url, quote, answer.code, index < len(answer.found) and answer.found[index]))
        return cls(tuple(checks))

    @classmethod
    def _ask(cls, sandbox: Sandbox, cited: List[Tuple[int, str, str]]) -> Dict[str, PageAnswer]:
        """One answer per distinct address, fetched in parallel batches."""
        by_url: Dict[str, List[str]] = {}
        for _, url, quote in cited:
            by_url.setdefault(url, []).append(quote)
        pages = sorted(by_url.items())
        batches = [pages[i:i + cls.BATCH] for i in range(0, len(pages), cls.BATCH)]
        with ThreadPoolExecutor(max_workers=cls.PARALLEL) as pool:
            answers = [answer for part in pool.map(sandbox.check_pages, batches) for answer in part]
        if len(answers) != len(pages):
            raise CatalogError(f"the sandbox answered {len(answers)} pages for {len(pages)}")
        return {url: answer for (url, _), answer in zip(pages, answers)}

    @classmethod
    def read(cls, path: Path) -> "RemoteReport":
        return cls(tuple(RemoteCheck(**doc) for doc in json.loads(path.read_text())))

    def write(self, path: Path) -> None:
        path.write_text(json.dumps([c.to_json() for c in self.checks], indent=1))

    def compare(self, local: LinkReport) -> Dict[str, int]:
        """How the sandbox's quote check lines up with this machine's, citation by citation."""
        if [(c.app_id, c.url) for c in local.checks] != [(c.app_id, c.url) for c in self.checks]:
            raise ValueError("the two reports do not cover the same citations in the same order")
        local_found = [c.quote is QuoteStatus.FOUND for c in local.checks]
        remote_found = [c.found for c in self.checks]
        both = sum(a and b for a, b in zip(local_found, remote_found))
        return {
            "citations": len(self.checks),
            "local_found": sum(local_found),
            "remote_found": sum(remote_found),
            "both_found": both,
            "only_local": sum(local_found) - both,
            "only_remote": sum(remote_found) - both,
        }
