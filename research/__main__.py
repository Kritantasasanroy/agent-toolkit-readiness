"""Command line: validate a pass, check its evidence, score it, and build the site data.

    python3 -m research validate runs/pass1
    python3 -m research links runs/pass1
    python3 -m research score runs/pass1 data/handchecks.json
    python3 -m research composio    (needs COMPOSIO_API_KEY)
    python3 -m research site
"""

import argparse
import json
import os
import sys
from pathlib import Path

from research.composio import CatalogError, ComposioCatalog
from research.handcheck import HandCheck, HandCheckError, Scorecard
from research.links import LinkReport
from research.paths import ROOT
from research.profile import ProfileError
from research.report import CaseStudy
from research.survey import Survey


def validate(args: argparse.Namespace) -> int:
    survey = Survey.load(Path(args.pass_dir))
    for name, reason in survey.rejected.items():
        print(f"{name}: {reason}")
    print(f"{len(survey.profiles)} valid, {len(survey.rejected)} rejected")
    return 1 if survey.rejected else 0


def links(args: argparse.Namespace) -> int:
    survey = Survey.load(Path(args.pass_dir))
    report = LinkReport.run(survey.all())
    out = ROOT / "runs" / "checks" / f"{survey.name}_links.json"
    report.write(out)
    print(json.dumps(report.totals(), indent=1))
    print(f"wrote {out.relative_to(ROOT)}")
    return 0


def score(args: argparse.Namespace) -> int:
    survey = Survey.load(Path(args.pass_dir))
    card = Scorecard.compare(survey.profiles, HandCheck.read_all(Path(args.handchecks)))
    print(f"{survey.name}: {card.accuracy():.1%} of {len(card.comparisons)} fields correct")
    for field, rate in card.accuracy_by_field().items():
        print(f"  {field.value:<14}{rate:.0%}")
    for miss in card.misses():
        print(f"  miss  {miss.app:<24}{miss.field.value:<14}agent={list(miss.agent)} truth={list(miss.truth)}")
    return 0


def composio(_args: argparse.Namespace) -> int:
    catalog = ComposioCatalog.fetch(os.environ.get("COMPOSIO_API_KEY", ""))
    catalog.write(ROOT / "data" / "composio_toolkits.json")
    print(f"wrote data/composio_toolkits.json ({len(catalog.toolkits)} toolkits)")
    return 0


def site(_args: argparse.Namespace) -> int:
    study = CaseStudy.build()
    study.render()
    print(f"wrote site/data.json and site/index.html ({len(study.final.profiles)} apps)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="research")
    commands = parser.add_subparsers(dest="command", required=True)
    for name, run in (("validate", validate), ("links", links)):
        command = commands.add_parser(name)
        command.add_argument("pass_dir")
        command.set_defaults(run=run)
    command = commands.add_parser("score")
    command.add_argument("pass_dir")
    command.add_argument("handchecks")
    command.set_defaults(run=score)
    commands.add_parser("composio").set_defaults(run=composio)
    commands.add_parser("site").set_defaults(run=site)
    args = parser.parse_args()
    try:
        return args.run(args)
    except (ProfileError, HandCheckError, CatalogError, ValueError) as err:
        print(f"error: {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
