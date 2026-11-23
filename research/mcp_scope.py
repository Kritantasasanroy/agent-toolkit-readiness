"""What an official MCP server can do: act on a customer's account, or only serve documentation, public data or tooling.

An agent reads the vendor's own pages and records one finding per app with a quote. A finding
only counts when its quote is found on the cited page, here or in the Composio sandbox.
"""

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Tuple

from research.composio import CatalogError
from research.links import Page, QuoteStatus
from research.profile import Doc, ProfileError
from research.remote import Sandbox


class Scope(Enum):
    ACCOUNT = "account"
    NO_ACCOUNT = "no_account"
    UNCLEAR = "unclear"


@dataclass(frozen=True)
class ScopeFinding:
    app_id: int
    app: str
    scope: Scope
    reason: str
    url: str
    quote: str

    @classmethod
    def from_json(cls, doc: Mapping[str, object]) -> "ScopeFinding":
        fields = Doc(doc)
        app_id = doc.get("app_id")
        if not isinstance(app_id, int):
            raise ProfileError(f"app_id: expected a number, got {app_id!r}")
        return cls(app_id, fields.text("app"), fields.enum(Scope, "scope"), fields.text("reason"),
                   fields.text("url"), fields.text("quote"))


@dataclass(frozen=True)
class ScopeCheck:
    """Whether a finding's quote was found on its page, from this machine and from the sandbox."""

    app_id: int
    local: QuoteStatus
    remote: bool

    @property
    def is_found(self) -> bool:
        return self.local is QuoteStatus.FOUND or self.remote

    def to_json(self) -> Dict[str, object]:
        return {"app_id": self.app_id, "local": self.local.value, "remote": self.remote}


@dataclass(frozen=True)
class McpScopes:
    findings: Tuple[ScopeFinding, ...]
    checks: Tuple[ScopeCheck, ...] = ()

    @classmethod
    def load(cls, directory: Path, checks_path: Path) -> "McpScopes":
        paths = sorted(directory.glob("*.json"), key=lambda p: int(p.stem))
        if not paths:
            raise ProfileError(f"no scope files in {directory}")
        findings = tuple(ScopeFinding.from_json(json.loads(path.read_text())) for path in paths)
        checks: List[ScopeCheck] = []
        if checks_path.exists():
            checks = [ScopeCheck(row["app_id"], QuoteStatus(row["local"]), bool(row["remote"]))
                      for row in json.loads(checks_path.read_text())]
        return cls(findings, tuple(checks))

    @classmethod
    def verify(cls, findings: Iterable[ScopeFinding], sandbox: Sandbox) -> Tuple[ScopeCheck, ...]:
        """Look for each quote here first, then in the sandbox for the ones this machine could not find."""
        findings = list(findings)
        local = {f.app_id: Page.fetch(f.url).quote_status(f.quote) for f in findings}
        retry = [f for f in findings if local[f.app_id] is not QuoteStatus.FOUND]
        remote: Dict[int, bool] = {}
        for start in range(0, len(retry), 20):
            batch = retry[start:start + 20]
            answers = sandbox.check_pages([(f.url, [f.quote]) for f in batch])
            if len(answers) != len(batch):
                raise CatalogError(f"the sandbox answered {len(answers)} pages for {len(batch)}")
            remote.update({f.app_id: answer.found[0] for f, answer in zip(batch, answers)})
        return tuple(ScopeCheck(f.app_id, local[f.app_id], remote.get(f.app_id, False)) for f in findings)

    def effective(self) -> Dict[int, Scope]:
        """The scope each app keeps once its quote is checked. A quote nobody could find downgrades it to unclear."""
        found = {check.app_id for check in self.checks if check.is_found}
        return {f.app_id: f.scope if f.app_id in found else Scope.UNCLEAR for f in self.findings}

    def counts(self) -> Dict[str, int]:
        scopes = list(self.effective().values())
        return {scope.value: scopes.count(scope) for scope in Scope}

    def unverified(self) -> int:
        """Findings that claimed a scope but whose quote could not be found."""
        effective = self.effective()
        return sum(f.scope is not Scope.UNCLEAR and effective[f.app_id] is Scope.UNCLEAR for f in self.findings)
