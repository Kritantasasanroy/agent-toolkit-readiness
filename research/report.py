"""Everything the published page shows, assembled from the saved passes and checks."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

from research.adjudication import Disputes
from research.browser import BrowserReport
from research.composio import ComposioCatalog, Coverage, Match
from research.handcheck import HandCheck, Scorecard
from research.independent import IndependentReview
from research.links import LinkReport
from research.mcp_scope import McpScopes
from research.paths import ROOT
from research.profile import Access, Field, Mcp, Verdict
from research.remote import RemoteReport
from research.survey import Survey


@dataclass(frozen=True)
class CaseStudy:
    first: Survey
    final: Survey
    checks: List[HandCheck]
    disputes: Disputes
    links_first: LinkReport
    links_final: LinkReport
    remote_final: RemoteReport
    mcp_scopes: McpScopes
    browser_final: BrowserReport
    independent: List[HandCheck]
    independent_review: IndependentReview
    independent_before: Dict[str, object]
    catalog: ComposioCatalog

    @classmethod
    def build(cls, root: Path = ROOT) -> "CaseStudy":
        study = cls._read(root)
        official = {p.app_id for p in study.final.all() if p.mcp is Mcp.OFFICIAL}
        scoped = {f.app_id for f in study.mcp_scopes.findings}
        if official != scoped:
            raise ValueError(f"MCP scope answers do not match the official servers: missing {sorted(official - scoped)}, extra {sorted(scoped - official)}")
        return study

    @classmethod
    def _read(cls, root: Path) -> "CaseStudy":
        return cls(
            first=Survey.load(root / "runs" / "pass1"),
            final=Survey.load(root / "runs" / "pass2"),
            checks=HandCheck.read_all(root / "data" / "handchecks.json"),
            disputes=Disputes.load(root),
            links_first=LinkReport.read(root / "runs" / "checks" / "pass1_links.json"),
            links_final=LinkReport.read(root / "runs" / "checks" / "pass2_links.json"),
            remote_final=RemoteReport.read(root / "runs" / "checks" / "pass2_remote_links.json"),
            independent=HandCheck.read_all(root / "data" / "independent_checks.json"),
            independent_review=IndependentReview.load(root / "runs" / "checks"),
            independent_before=json.loads((root / "runs" / "checks" / "independent_scores_before.json").read_text()),
            browser_final=BrowserReport.read(root / "runs" / "checks" / "pass2_browser_links.json"),
            mcp_scopes=McpScopes.load(root / "runs" / "mcp_scope", root / "runs" / "checks" / "mcp_scope_quotes.json"),
            catalog=ComposioCatalog.read(root / "data" / "composio_toolkits.json"),
        )

    def auth_check(self, coverage: Dict[str, Match]) -> Dict[str, object]:
        """Our auth answers against Composio's, for apps with a native toolkit: a source the
        research agents did not write."""
        native = [p for p in self.final.all() if coverage[p.app].coverage is Coverage.NATIVE]
        extras = {p.app: (p, coverage[p.app].auth_not_in(p.auth_methods)) for p in native}
        differ = [{"app": app, "ours": p.answer(Field.AUTH_METHODS), "extra_in_composio": extra}
                  for app, (p, extra) in extras.items() if extra]
        return {"checked": len(native), "consistent": len(native) - len(differ), "differ": differ}

    def gated_but_built(self, coverage: Dict[str, Match]) -> List[str]:
        """Apps I marked as needing outreach or gated that Composio already has a native toolkit for."""
        return [p.app for p in self.final.all()
                if coverage[p.app].coverage is Coverage.NATIVE
                and (p.verdict is Verdict.NEEDS_OUTREACH or p.access in (Access.PARTNER_GATED, Access.ADMIN_APPROVAL))]

    def independent_json(self) -> Dict[str, object]:
        """The blind browser check on twenty more apps: scores before any correction, the rulings on
        every disagreement, and the score once the corrections those rulings called for are in."""
        after = Scorecard.compare(self.final.profiles, self.independent)
        before = self.independent_before
        return {
            "apps": len(self.independent),
            "before_pass1": before["pass1"],
            "before_pass2": before["pass2"],
            "after": after.to_json(),
            "tally": self.independent_review.tally(),
            "corrected": sum(i.winner.value == "reference" for i in self.independent_review.items),
            "rulings": self.independent_review.to_json(),
        }

    def to_json(self) -> Dict[str, object]:
        contested = self.disputes.contested_fields()
        coverage = {p.app: self.catalog.lookup(p.app) for p in self.final.all()}
        scopes = self.mcp_scopes.effective()
        return {
            "apps": [dict(p.to_json(), contested=contested.get(p.app, []), composio=coverage[p.app].to_json(),
                          mcp_scope=scopes[p.app_id].value if p.app_id in scopes else "")
                     for p in self.final.all()],
            "composio": {
                "auth": self.auth_check(coverage),
                "gated_but_built": self.gated_but_built(coverage),
                "catalog_fetched": self.catalog.fetched,
                "catalog_size": len(self.catalog.toolkits),
                "coverage": {c.value: sum(m.coverage is c for m in coverage.values()) for c in Coverage},
            },
            "patterns": {
                "primary_auth": self.final.primary_auth(),
                "auth_mix": self.final.auth_mix(),
                "verdicts": self.final.verdicts(),
                "blockers": self.final.blockers(),
                "mcp": self.final.mcp_coverage(),
                "mcp_scope": dict(self.mcp_scopes.counts(), unverified=self.mcp_scopes.unverified()),
                "access_by_category": self.final.access_by_category(),
                "self_serve_by_category": self.final.self_serve_share_by_category(),
            },
            "verification": {
                "pass1": Scorecard.compare(self.first.profiles, self.checks).to_json(),
                "pass2": Scorecard.compare(self.final.profiles, self.checks).to_json(),
                "reference_leniency": HandCheck.leniency(self.checks),
                "links_pass1": self.links_first.totals(),
                "links_pass2": self.links_final.totals(),
                "links_pass2_composio": self.remote_final.compare(self.links_final),
                "links_pass2_combined": self.browser_final.combine(self.links_final, self.remote_final),
                "changed_fields": self.final.changes_since(self.first),
                "disputes": [d.to_json() for d in self.disputes.items],
                "dispute_tally": self.disputes.tally(),
                "to_review": self.disputes.to_review(),
                "human_reviewed": self.disputes.reviewed(),
                "rechecked": self.disputes.rechecked(),
                "independent": self.independent_json(),
                "hand_checks": [{"app": c.app, "sources": list(c.sources), "note": c.note} for c in self.checks],
            },
        }

    def render(self, root: Path = ROOT) -> Path:
        """Write site/data.json and site/index.html; returns the page path."""
        data = self.to_json()
        site_dir, src_dir = root / "site", root / "site_src"
        (site_dir / "data.json").write_text(json.dumps(data, indent=1))
        copy = (src_dir / "copy.html").read_text()
        # Inlined as well as written beside the page, so it works when opened straight from disk.
        inline = json.dumps(data).replace("</", "<\\/")
        page = (src_dir / "template.html").read_text().replace("<!--COPY-->", copy).replace("/*DATA*/", inline)
        out = site_dir / "index.html"
        out.write_text(page)
        return out
