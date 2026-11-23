"""Everything the published page shows, assembled from the saved passes and checks."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

from research.adjudication import Disputes
from research.composio import ComposioCatalog, Coverage, Match
from research.handcheck import HandCheck, Scorecard
from research.links import LinkReport
from research.paths import ROOT
from research.profile import Field
from research.survey import Survey


@dataclass(frozen=True)
class CaseStudy:
    first: Survey
    final: Survey
    checks: List[HandCheck]
    disputes: Disputes
    links_first: LinkReport
    links_final: LinkReport
    catalog: ComposioCatalog

    @classmethod
    def build(cls, root: Path = ROOT) -> "CaseStudy":
        return cls(
            first=Survey.load(root / "runs" / "pass1"),
            final=Survey.load(root / "runs" / "pass2"),
            checks=HandCheck.read_all(root / "data" / "handchecks.json"),
            disputes=Disputes.load(root),
            links_first=LinkReport.read(root / "runs" / "checks" / "pass1_links.json"),
            links_final=LinkReport.read(root / "runs" / "checks" / "pass2_links.json"),
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

    def to_json(self) -> Dict[str, object]:
        contested = self.disputes.contested_fields()
        coverage = {p.app: self.catalog.lookup(p.app) for p in self.final.all()}
        return {
            "apps": [dict(p.to_json(), contested=contested.get(p.app, []), composio=coverage[p.app].to_json())
                     for p in self.final.all()],
            "composio": {
                "auth": self.auth_check(coverage),
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
                "access_by_category": self.final.access_by_category(),
                "self_serve_by_category": self.final.self_serve_share_by_category(),
            },
            "verification": {
                "pass1": Scorecard.compare(self.first.profiles, self.checks).to_json(),
                "pass2": Scorecard.compare(self.final.profiles, self.checks).to_json(),
                "reference_leniency": HandCheck.leniency(self.checks),
                "links_pass1": self.links_first.totals(),
                "links_pass2": self.links_final.totals(),
                "changed_fields": self.final.changes_since(self.first),
                "disputes": [d.to_json() for d in self.disputes.items],
                "dispute_tally": self.disputes.tally(),
                "to_review": self.disputes.to_review(),
                "human_reviewed": self.disputes.reviewed(),
                "rechecked": self.disputes.rechecked(),
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
