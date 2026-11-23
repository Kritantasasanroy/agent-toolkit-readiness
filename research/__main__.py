"""Command line: validate a pass, check its evidence, score it, and build the site data.

    python3 -m research validate runs/pass1
    python3 -m research links runs/pass1
    python3 -m research score runs/pass1 data/handchecks.json
    python3 -m research composio    (needs COMPOSIO_API_KEY)
    python3 -m research remote runs/pass2    (needs COMPOSIO_API_KEY)
    python3 -m research scope    (needs COMPOSIO_API_KEY)
    python3 -m research review   (needs COMPOSIO_API_KEY)
    python3 -m research site
"""

import argparse
import json
import os
import sys
from pathlib import Path

from research.composio import CatalogError, ComposioCatalog
from research.handcheck import HandCheck, HandCheckError, Scorecard
from research.independent import IndependentReview
from research.links import LinkReport
from research.mcp_scope import McpScopes
from research.paths import ROOT
from research.profile import ProfileError
from research.remote import RemoteReport, Sandbox
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
    checks = HandCheck.read_all(Path(args.handchecks))
    if args.skip_missing:
        skipped = [c.app for c in checks if c.app_id not in survey.profiles]
        checks = [c for c in checks if c.app_id in survey.profiles]
        print(f"skipped {len(skipped)} apps with no valid profile: {', '.join(skipped) or 'none'}")
    card = Scorecard.compare(survey.profiles, checks)
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


def remote(args: argparse.Namespace) -> int:
    survey = Survey.load(Path(args.pass_dir))
    local_path = ROOT / "runs" / "checks" / f"{survey.name}_links.json"
    if not local_path.exists():
        raise CatalogError(f"run `research links {args.pass_dir}` first: {local_path.name} is missing")
    local = LinkReport.read(local_path)
    report = RemoteReport.run(survey.all(), Sandbox.open(os.environ.get("COMPOSIO_API_KEY", "")))
    out = ROOT / "runs" / "checks" / f"{survey.name}_remote_links.json"
    report.write(out)
    print(json.dumps(report.compare(local), indent=1))
    print(f"wrote {out.relative_to(ROOT)}")
    return 0


def scope(_args: argparse.Namespace) -> int:
    directory, checks = ROOT / "runs" / "mcp_scope", ROOT / "runs" / "checks" / "mcp_scope_quotes.json"
    scopes = McpScopes.load(directory, checks)
    results = McpScopes.verify(scopes.findings, Sandbox.open(os.environ.get("COMPOSIO_API_KEY", "")))
    checks.write_text(json.dumps([c.to_json() for c in results], indent=1))
    print(json.dumps(McpScopes(scopes.findings, results).counts()))
    print(f"wrote {checks.relative_to(ROOT)}")
    return 0


def review(_args: argparse.Namespace) -> int:
    checks = ROOT / "runs" / "checks"
    IndependentReview.probe(checks / "independent_quotes.json", checks, Sandbox.open(os.environ.get("COMPOSIO_API_KEY", "")))
    print(json.dumps(IndependentReview.load(checks).tally()))
    print("wrote runs/checks/independent_quotes.json")
    return 0


def site(_args: argparse.Namespace) -> int:
    study = CaseStudy.build(ROOT)
    study.render(ROOT)
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
    command.add_argument("--skip-missing", action="store_true", help="score only apps that have a valid profile")
    command.set_defaults(run=score)
    commands.add_parser("composio").set_defaults(run=composio)
    command = commands.add_parser("remote")
    command.add_argument("pass_dir")
    command.set_defaults(run=remote)
    commands.add_parser("scope").set_defaults(run=scope)
    commands.add_parser("review").set_defaults(run=review)
    commands.add_parser("site").set_defaults(run=site)
    args = parser.parse_args()
    try:
        return args.run(args)
    except (ProfileError, HandCheckError, CatalogError, ValueError) as err:
        print(f"error: {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
