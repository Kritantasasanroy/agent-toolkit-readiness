"""Hand-checked answers for a sample of apps, and how a survey scores against them."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Mapping, Tuple

from research.profile import Field, Profile


class HandCheckError(ValueError):
    pass


@dataclass(frozen=True)
class HandCheck:
    app_id: int
    app: str
    answers: Mapping[Field, Tuple[str, ...]]
    sources: Tuple[str, ...]
    note: str

    @classmethod
    def from_json(cls, doc: Mapping[str, object]) -> "HandCheck":
        app = doc.get("app")
        if not isinstance(app, str) or not app:
            raise HandCheckError(f"hand check has no app name: {doc!r}")
        answers: Dict[Field, Tuple[str, ...]] = {}
        for field in Field:
            raw = doc.get(field.value)
            values = raw if isinstance(raw, list) else [raw]
            allowed = {member.value for member in field.allowed}
            bad = [value for value in values if value not in allowed]
            if not values or bad:
                raise HandCheckError(f"hand check for {app}: {field.value} has {bad or 'no answer'}")
            answers[field] = tuple(str(value) for value in values)
        app_id = doc.get("app_id")
        if not isinstance(app_id, int):
            raise HandCheckError(f"hand check for {app}: app_id must be a number, got {app_id!r}")
        sources = doc.get("sources", [])
        if not isinstance(sources, list):
            raise HandCheckError(f"hand check for {app}: sources must be a list")
        return cls(
            app_id=app_id,
            app=app,
            answers=answers,
            sources=tuple(str(url) for url in sources),
            note=str(doc.get("note", "")),
        )

    @classmethod
    def read_all(cls, path: Path) -> List["HandCheck"]:
        try:
            docs = json.loads(path.read_text())
        except json.JSONDecodeError as err:
            raise HandCheckError(f"{path.name} is not valid JSON: {err}") from err
        return [cls.from_json(doc) for doc in docs]

    def accepts(self, field: Field, answer: List[str]) -> bool:
        """A list field scores a correct first answer plus any subset of the accepted values,
        so a missing value is never penalised: those scores measure precision, not recall.
        A single field needs exactly one value from the accepted set, which holds more than
        one reading where the docs honestly support two."""
        truth = self.answers[field]
        if field.is_list:
            return bool(answer) and answer[0] in truth and set(answer) <= set(truth)
        return len(answer) == 1 and answer[0] in truth

    @classmethod
    def leniency(cls, checks: List["HandCheck"]) -> Dict[str, int]:
        """How many single-value answers accept more than one reading, and in how many apps."""
        singles = [f for f in Field if not f.is_list]
        return {
            "single_answers": len(checks) * len(singles),
            "accepting_several": sum(len(c.answers[f]) > 1 for c in checks for f in singles),
            "apps_with_several": sum(c.is_lenient() for c in checks),
            "apps": len(checks),
        }

    def is_lenient(self) -> bool:
        """True when any single-value field accepts more than one reading."""
        return any(len(self.answers[f]) > 1 for f in Field if not f.is_list)


@dataclass(frozen=True)
class Comparison:
    app_id: int
    app: str
    field: Field
    agent: Tuple[str, ...]
    truth: Tuple[str, ...]
    correct: bool


@dataclass(frozen=True)
class Scorecard:
    comparisons: Tuple[Comparison, ...]

    @classmethod
    def compare(cls, profiles: Mapping[int, Profile], checks: List[HandCheck]) -> "Scorecard":
        if not checks:
            raise HandCheckError("no hand checks to score against")
        comparisons = []
        for check in checks:
            profile = profiles.get(check.app_id)
            if profile is None:
                raise HandCheckError(f"hand check for {check.app} has no profile in this pass")
            for field in Field:
                answer = profile.answer(field)
                comparisons.append(Comparison(
                    app_id=check.app_id,
                    app=check.app,
                    field=field,
                    agent=tuple(answer),
                    truth=check.answers[field],
                    correct=check.accepts(field, answer),
                ))
        return cls(tuple(comparisons))

    def accuracy(self) -> float:
        return sum(c.correct for c in self.comparisons) / len(self.comparisons)

    def accuracy_by_field(self) -> Dict[Field, float]:
        by_field: Dict[Field, List[bool]] = {}
        for c in self.comparisons:
            by_field.setdefault(c.field, []).append(c.correct)
        return {field: sum(hits) / len(hits) for field, hits in by_field.items()}

    def misses(self) -> List[Comparison]:
        return [c for c in self.comparisons if not c.correct]

    def to_json(self) -> Dict[str, object]:
        return {
            "accuracy": round(self.accuracy(), 3),
            "fields_checked": len(self.comparisons),
            "apps_checked": len({c.app_id for c in self.comparisons}),
            "by_field": {f.value: round(rate, 3) for f, rate in self.accuracy_by_field().items()},
            "misses": [
                {"app": c.app, "field": c.field.value, "agent": list(c.agent), "truth": list(c.truth)}
                for c in self.misses()
            ],
        }
