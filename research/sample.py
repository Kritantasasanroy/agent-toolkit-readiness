"""The reference sample: a fixed number of apps per category, drawn with a fixed seed."""

import csv
import random
from pathlib import Path
from typing import Dict, List


class Sample:
    SEED = 2026
    PER_CATEGORY = 2

    @classmethod
    def draw(cls, apps_csv: Path) -> List[int]:
        """App ids in the order they were drawn, category by category in file order."""
        by_category: Dict[str, List[int]] = {}
        with apps_csv.open(newline="") as handle:
            for row in csv.DictReader(handle):
                by_category.setdefault(row["category"], []).append(int(row["id"]))
        rng = random.Random(cls.SEED)
        return [app_id for ids in by_category.values() for app_id in rng.sample(ids, cls.PER_CATEGORY)]
