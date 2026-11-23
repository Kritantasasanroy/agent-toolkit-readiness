"""The independent check: answers written blind in a browser, and a ruling on every disagreement.

Twenty apps, drawn with a second seed, were researched in a browser by agents that never saw the
pipeline's answers. Wherever the pipeline and that reference differ, a fresh browser agent saw the
two answers shuffled and unlabelled and ruled from the vendor's pages. A ruling only counts when its
quote is found on the cited page, here or in the Composio sandbox.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Mapping, Tuple

from research.adjudication import Ruling, Side, Winner
from research.profile import Doc, Field, ProfileError
from research.remote import Probe, Sandbox


@dataclass(frozen=True)
class Disagreement:
    item: int
    app_id: int
    app: str
    field: Field
    a_is: Side
    ruling: Ruling
    source: str
    quote: str
    note: str
    confirmed: bool

    @property
    def winner(self) -> Winner:
        """Whose answer the docs back. A ruling whose quote nobody could find counts as unclear."""
        return self.ruling.resolve(self.a_is) if self.confirmed else Winner.UNCLEAR


@dataclass(frozen=True)
class IndependentReview:
    items: Tuple[Disagreement, ...]

    @staticmethod
    def _rulings(checks_dir: Path) -> Dict[int, Mapping[str, object]]:
        rulings: Dict[int, Mapping[str, object]] = {}
        for path in sorted(checks_dir.glob("independent_rulings_*.json")):
            rulings.update({row["item"]: row for row in json.loads(path.read_text())})
        return rulings

    @staticmethod
    def _confirmed(checks_dir: Path) -> Dict[int, bool]:
        """Which rulings had their quote found here, in the sandbox or in a browser."""
        path = checks_dir / "independent_quotes.json"
        rows = json.loads(path.read_text()) if path.exists() else []
        return {row["item"]: row["local"] == "found" or bool(row["remote"]) for row in rows}

    @classmethod
    def load(cls, checks_dir: Path) -> "IndependentReview":
        key = {row["item"]: row for row in json.loads((checks_dir / "independent_key.json").read_text())}
        rulings, confirmed = cls._rulings(checks_dir), cls._confirmed(checks_dir)
        if set(rulings) != set(key):
            raise ProfileError(f"rulings cover items {sorted(rulings)}, the key has {sorted(key)}")
        items: List[Disagreement] = []
        for number, row in sorted(key.items()):
            fields = Doc(rulings[number])
            items.append(Disagreement(
                item=number, app_id=row["app_id"], app=row["app"], field=Field(row["field"]),
                a_is=Side.REFERENCE if row["A_is"] == "independent" else Side.AGENT,
                ruling=Ruling(rulings[number]["ruling"]), source=fields.text("source"), quote=fields.text("quote"),
                note=fields.text("note"), confirmed=confirmed.get(number, False)))
        return cls(tuple(items))

    @staticmethod
    def probe(path: Path, checks_dir: Path, sandbox: Sandbox) -> None:
        """Look for every ruling's quote on its page and save where it was found."""
        review = IndependentReview.load(checks_dir)
        probes = Probe.run([(i.source, i.quote) for i in review.items], sandbox)
        path.write_text(json.dumps([
            {"item": i.item, "local": p.local.value, "remote": p.remote} for i, p in zip(review.items, probes)], indent=1))

    def tally(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for item in self.items:
            counts[item.winner.value] = counts.get(item.winner.value, 0) + 1
        return counts

    def to_json(self) -> List[Dict[str, object]]:
        return [{"item": i.item, "app": i.app, "field": i.field.value, "winner": i.winner.value,
                 "source": i.source, "quote": i.quote, "note": i.note} for i in self.items]
