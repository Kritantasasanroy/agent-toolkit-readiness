"""All the profiles from one research pass, and what they say as a whole."""

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Mapping, Tuple

from research.profile import Access, Field, Profile, ProfileError, Verdict


@dataclass(frozen=True)
class Survey:
    name: str
    profiles: Mapping[int, Profile]
    rejected: Mapping[str, str]

    @classmethod
    def load(cls, directory: Path) -> "Survey":
        """Read every <app_id>.json in a pass directory, keeping rejects and their reasons."""
        paths = sorted(directory.glob("*.json"))
        if not paths:
            raise ProfileError(f"no profile files in {directory}")
        profiles: Dict[int, Profile] = {}
        rejected: Dict[str, str] = {}
        for path in paths:
            try:
                profile = Profile.read(path)
                if path.stem != str(profile.app_id):
                    raise ProfileError(f"file name does not match app_id {profile.app_id}")
            except ProfileError as err:
                rejected[path.name] = str(err)
                continue
            profiles[profile.app_id] = profile
        return cls(directory.name, profiles, rejected)

    def all(self) -> List[Profile]:
        return [self.profiles[app_id] for app_id in sorted(self.profiles)]

    def auth_mix(self) -> Dict[str, int]:
        """How many apps support each auth method; an app counts once per method."""
        counts = Counter(m.value for p in self.all() for m in set(p.auth_methods))
        return dict(counts.most_common())

    def primary_auth(self) -> Dict[str, int]:
        return dict(Counter(p.auth_methods[0].value for p in self.all()).most_common())

    def access_by_category(self) -> Dict[str, Dict[str, int]]:
        table: Dict[str, Dict[str, int]] = {}
        for p in self.all():
            row = table.setdefault(p.category, {access.value: 0 for access in Access})
            row[p.access.value] += 1
        return table

    def self_serve_share_by_category(self) -> List[Tuple[str, float]]:
        groups: Dict[str, List[bool]] = {}
        for p in self.all():
            groups.setdefault(p.category, []).append(p.access.is_self_serve)
        shares = [(category, sum(flags) / len(flags)) for category, flags in groups.items()]
        return sorted(shares, key=lambda pair: pair[1], reverse=True)

    def blockers(self) -> Dict[str, int]:
        return dict(Counter(p.blocker.value for p in self.all()).most_common())

    def verdicts(self) -> Dict[str, int]:
        return {v.value: sum(p.verdict is v for p in self.all()) for v in Verdict}

    def mcp_coverage(self) -> Dict[str, int]:
        return dict(Counter(p.mcp.value for p in self.all()).most_common())

    def changes_since(self, earlier: "Survey") -> List[Dict[str, object]]:
        """Every scored field whose answer differs from the earlier pass."""
        changes: List[Dict[str, object]] = []
        for profile in self.all():
            before = earlier.profiles.get(profile.app_id)
            if before is None:
                continue
            for field in Field:
                if before.answer(field) != profile.answer(field):
                    changes.append({
                        "app": profile.app,
                        "field": field.value,
                        "before": before.answer(field),
                        "after": profile.answer(field),
                    })
        return changes
