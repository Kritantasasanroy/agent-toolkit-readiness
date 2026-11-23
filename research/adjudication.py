"""Disputed answers: where two passes, or a pass and the reference sample, disagreed.

Each dispute was shown to a fresh agent as two shuffled, unlabelled options and settled from
the vendor's docs. Two later layers can change the outcome, and the later one wins:
a labelled override (data/overrides.json, a correction made by the author with evidence)
and a human decision (data/decisions.json, what a person ruled after reading the sources).
"""

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Dict, List, Mapping, Tuple

from research.paths import ROOT
from research.profile import Field


class Kind(Enum):
    CHANGED = "changed"          # pass 2 changed what pass 1 said
    SAMPLE_MISS = "sample_miss"  # the agent disagreed with the reference sample

    def allows(self, winner: "Winner") -> bool:
        """Whether the winner is one of the possible outcomes for this kind of dispute."""
        sides = (Winner.PASS1, Winner.PASS2) if self is Kind.CHANGED else (Winner.AGENT, Winner.REFERENCE)
        return winner in sides + (Winner.BOTH, Winner.NEITHER, Winner.UNCLEAR)


class Side(Enum):
    PASS1 = "pass1"
    PASS2 = "pass2"
    AGENT = "agent"
    REFERENCE = "reference"

    def other(self) -> "Side":
        pairs = {Side.PASS1: Side.PASS2, Side.PASS2: Side.PASS1,
                 Side.AGENT: Side.REFERENCE, Side.REFERENCE: Side.AGENT}
        return pairs[self]


class Ruling(Enum):
    A = "A"
    B = "B"
    BOTH = "both"
    NEITHER = "neither"
    UNCLEAR = "unclear"

    def resolve(self, a_is: "Side") -> "Winner":
        """Whose answer this ruling supports, given which side was shown as option A."""
        if self is Ruling.A:
            return Winner(a_is.value)
        if self is Ruling.B:
            return Winner(a_is.other().value)
        return Winner(self.value)


class Winner(Enum):
    """Whose answer the docs supported, or why no one's was."""

    PASS1 = "pass1"
    PASS2 = "pass2"
    AGENT = "agent"
    REFERENCE = "reference"
    BOTH = "both"
    NEITHER = "neither"
    UNCLEAR = "unclear"


class Decider(Enum):
    BLIND_CHECK = "fresh agent check"
    EVIDENCE_OVERRIDE = "live test"
    STRICT_RECHECK = "docs re-read"
    HUMAN = "reviewed by hand"


@dataclass(frozen=True)
class Dispute:
    item: int
    app: str
    field: Field
    kind: Kind
    source: str
    quote: str
    note: str
    winner: Winner
    decider: Decider
    blind_winner: Winner

    @property
    def needs_review(self) -> bool:
        """A change the blind check did not back, so it needs a second look."""
        return self.kind is Kind.CHANGED and self.blind_winner is not Winner.PASS2

    @property
    def is_contested(self) -> bool:
        return self.needs_review and self.decider in (Decider.BLIND_CHECK, Decider.EVIDENCE_OVERRIDE)

    def to_json(self) -> Dict[str, object]:
        return {
            "item": self.item, "app": self.app, "field": self.field.value, "kind": self.kind.value,
            "winner": self.winner.value, "decided_by": self.decider.value,
            "source": self.source, "quote": self.quote, "note": self.note,
        }


@dataclass(frozen=True)
class Disputes:
    items: Tuple[Dispute, ...]

    @staticmethod
    def _read_rows(path: Path) -> List[Mapping[str, object]]:
        return json.loads(path.read_text()) if path.exists() else []

    @staticmethod
    def _settle(number: int, row: Mapping[str, object], ruling: Mapping[str, object],
                override: Mapping[str, object], decision: Mapping[str, object]) -> Dispute:
        """The blind ruling, replaced by an override, then by a decision: the later layer wins."""
        blind = Ruling(ruling["ruling"]).resolve(Side(row["A_is"]))
        winner, decider, note = blind, Decider.BLIND_CHECK, ruling.get("note", "")
        if override:
            winner, decider, note = Winner(override["winner"]), Decider.EVIDENCE_OVERRIDE, override["note"]
        if decision:
            winner = Winner(decision["decision"])
            decider = Decider.STRICT_RECHECK if decision.get("by") == "agent" else Decider.HUMAN
            note = decision.get("note", note)
        if not Kind(row["kind"]).allows(winner):
            raise ValueError(f"item {number}: {winner.value} is not a possible winner of a {row['kind']} dispute")
        return Dispute(
            item=number, app=row["app"], field=Field(row["field"]), kind=Kind(row["kind"]),
            source=ruling.get("source", ""), quote=ruling.get("quote", ""), note=note,
            winner=winner, decider=decider, blind_winner=blind,
        )

    @classmethod
    def load(cls, root: Path = ROOT) -> "Disputes":
        checks = root / "runs" / "checks"
        key = {row["item"]: row for row in cls._read_rows(checks / "adjudication_key.json")}
        rulings = {row["item"]: row for suffix in ("a", "b")
                   for row in cls._read_rows(checks / f"adjudication_rulings_{suffix}.json")}
        overrides = {row["item"]: row for row in cls._read_rows(root / "data" / "overrides.json")}
        decisions = {row["item"]: row for row in cls._read_rows(root / "data" / "decisions.json")}
        for name, rows in (("rulings", rulings), ("overrides", overrides), ("decisions", decisions)):
            unknown = sorted(set(rows) - set(key))
            if unknown:
                raise ValueError(f"{name} refer to items that are not in the key: {unknown}")
        missing = sorted(set(key) - set(rulings))
        if missing:
            raise ValueError(f"no ruling for items {missing}")
        items = [cls._settle(number, row, rulings[number], overrides.get(number, {}), decisions.get(number, {}))
                 for number, row in sorted(key.items())]
        return cls(tuple(items))

    def tally(self) -> Dict[str, Dict[str, int]]:
        """Winner counts, separately for pass-1/pass-2 changes and for sample misses."""
        totals: Dict[str, Dict[str, int]] = {}
        for dispute in self.items:
            bucket = totals.setdefault(dispute.kind.value, {})
            bucket[dispute.winner.value] = bucket.get(dispute.winner.value, 0) + 1
        return totals

    def contested_fields(self) -> Dict[str, List[str]]:
        contested: Dict[str, List[str]] = {}
        for dispute in self.items:
            if dispute.is_contested:
                contested.setdefault(dispute.app, []).append(dispute.field.value)
        return contested

    def to_review(self) -> int:
        return sum(d.needs_review for d in self.items)

    def reviewed(self) -> int:
        return sum(d.needs_review and d.decider is Decider.HUMAN for d in self.items)

    def rechecked(self) -> int:
        return sum(d.needs_review and d.decider is Decider.STRICT_RECHECK for d in self.items)
