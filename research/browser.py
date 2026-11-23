"""The third look at the evidence: a real browser, for citations the plain fetch could not confirm.

The loop lives in research/browser_check.js and runs through the BrowserOS tool. Its results are
kept in runs/checks/pass2_browser_links.json and combined here with the local and sandbox checks.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Set, Tuple

from research.links import LinkReport, QuoteStatus
from research.remote import RemoteReport


@dataclass(frozen=True)
class BrowserCheck:
    app_id: int
    url: str
    quote: str
    found: bool


@dataclass(frozen=True)
class BrowserReport:
    checks: Tuple[BrowserCheck, ...]

    @classmethod
    def read(cls, path: Path) -> "BrowserReport":
        return cls(tuple(BrowserCheck(**doc) for doc in json.loads(path.read_text())))

    def combine(self, local: LinkReport, remote: RemoteReport) -> Dict[str, int]:
        """How many citations at least one of the three checks confirmed, and what the browser added."""
        if [(c.app_id, c.url) for c in local.checks] != [(c.app_id, c.url) for c in remote.checks]:
            raise ValueError("the local and sandbox reports do not cover the same citations in the same order")
        seen: Set[Tuple[int, str, str]] = {(c.app_id, c.url, c.quote) for c in self.checks if c.found}
        confirmed = by_browser = 0
        for here, there in zip(local.checks, remote.checks):
            if here.quote is QuoteStatus.FOUND or there.found:
                confirmed += 1
            elif (there.app_id, there.url, there.quote) in seen:
                confirmed += 1
                by_browser += 1
        return {"citations": len(local.checks), "confirmed": confirmed, "browser_added": by_browser}
