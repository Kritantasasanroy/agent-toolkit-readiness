import base64
import contextlib
import gzip
import shutil
import http.server
import io
import json
import os
import re
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Dict, List
from unittest import mock

from research.adjudication import Decider, Disputes, Winner
from research.__main__ import main
from research.composio import CatalogError, ComposioCatalog, Coverage, Match, Toolkit
from research.handcheck import HandCheck, HandCheckError, Scorecard
from research.browser import BrowserCheck, BrowserReport
from research.independent import IndependentReview
from research.mcp_scope import McpScopes, Scope, ScopeCheck, ScopeFinding
from research.links import LinkCheck, LinkReport, Page, PageStatus, QuoteStatus
from research.profile import Access, ApiStyle, AuthMethod, Doc, Field, Profile, ProfileError
from research.paths import ROOT
from research import remote_check
from research.remote import PageAnswer, RemoteCheck, RemoteReport, Sandbox
from research.report import CaseStudy
from research.sample import Sample
from research.survey import Survey


def profile_doc(**overrides: object) -> Dict[str, object]:
    doc = {
        "app_id": 61,
        "app": "GitHub",
        "category": "Developer, Infra and Data platforms",
        "summary": "Code hosting and collaboration.",
        "auth_methods": ["oauth2", "api_key"],
        "access": "free_self_serve",
        "access_note": "",
        "api_styles": ["rest", "graphql"],
        "api_breadth": "broad",
        "mcp": "official",
        "mcp_url": "https://github.com/github/github-mcp-server",
        "verdict": "build_now",
        "blocker": "none",
        "blocker_note": "",
        "evidence": [
            {"field": f, "url": "https://docs.github.com/rest", "quote": "q"}
            for f in ("auth_methods", "access", "api_styles", "mcp")
        ],
        "confidence": "high",
        "notes": "",
    }
    doc.update(overrides)
    return doc


def hand_check_doc(**overrides: object) -> Dict[str, object]:
    doc = {
        "app_id": 61,
        "app": "GitHub",
        "auth_methods": ["oauth2", "api_key", "bearer_token"],
        "access": "free_self_serve",
        "api_styles": ["rest", "graphql"],
        "mcp": "official",
        "verdict": "build_now",
        "blocker": "none",
    }
    doc.update(overrides)
    return doc


class ProfileTest(unittest.TestCase):
    def test_reads_a_complete_profile(self) -> None:
        profile = Profile.from_json(profile_doc())
        self.assertEqual(profile.answer(Field.AUTH_METHODS), ["oauth2", "api_key"])
        self.assertTrue(profile.access.is_self_serve)

    def test_rejects_a_value_outside_the_brief(self) -> None:
        with self.assertRaisesRegex(ProfileError, "access: 'free'"):
            Profile.from_json(profile_doc(access="free"))

    def test_rejects_a_cited_field_with_no_evidence(self) -> None:
        evidence = [{"field": "access", "url": "https://x.io", "quote": "q"}]
        with self.assertRaisesRegex(ProfileError, "no evidence for auth_methods"):
            Profile.from_json(profile_doc(evidence=evidence))

    def test_rejects_an_mcp_claim_without_a_link(self) -> None:
        with self.assertRaisesRegex(ProfileError, "mcp_url is empty"):
            Profile.from_json(profile_doc(mcp="community", mcp_url=""))


class ScorecardTest(unittest.TestCase):
    def test_list_field_needs_a_correct_first_answer_and_nothing_wrong(self) -> None:
        check = HandCheck.from_json(hand_check_doc())
        self.assertTrue(check.accepts(Field.AUTH_METHODS, ["oauth2"]))
        self.assertFalse(check.accepts(Field.AUTH_METHODS, ["oauth2", "basic"]))
        self.assertFalse(check.accepts(Field.AUTH_METHODS, []))

    def test_a_single_value_field_accepts_any_listed_reading_and_nothing_else(self) -> None:
        check = HandCheck.from_json(hand_check_doc(access=["free_self_serve", "free_trial"]))
        self.assertTrue(check.accepts(Field.ACCESS, ["free_trial"]))
        self.assertFalse(check.accepts(Field.ACCESS, ["paid_plan"]))
        self.assertFalse(check.accepts(Field.ACCESS, ["free_trial", "free_self_serve"]))

    def test_counts_misses_per_field(self) -> None:
        profiles = {61: Profile.from_json(profile_doc(mcp="none", mcp_url=""))}
        card = Scorecard.compare(profiles, [HandCheck.from_json(hand_check_doc())])
        self.assertEqual([m.field for m in card.misses()], [Field.MCP])
        self.assertAlmostEqual(card.accuracy(), 5 / 6)

    def test_refuses_a_hand_check_with_no_profile(self) -> None:
        with self.assertRaisesRegex(HandCheckError, "no profile"):
            Scorecard.compare({}, [HandCheck.from_json(hand_check_doc())])


class PageTest(unittest.TestCase):
    def test_finds_a_quote_despite_markup_and_typographic_quotes(self) -> None:
        text = Page.normalise(Page.readable("<p>Use  an <b>API</b>\nkey</p><script>var key;</script>"))
        page = Page("https://x.io", PageStatus.LIVE, 200, text)
        self.assertIs(page.quote_status("use an API key"), QuoteStatus.FOUND)
        self.assertIs(page.quote_status("var key"), QuoteStatus.MISSING)
        page = Page("https://x.io", PageStatus.LIVE, 200, Page.normalise("It’s a free   plan"))
        self.assertIs(page.quote_status("It's a free plan"), QuoteStatus.FOUND)

    def test_leaves_quotes_unchecked_when_the_page_did_not_load(self) -> None:
        page = Page("https://x.io", PageStatus.REFUSED, 403, "")
        self.assertIs(page.quote_status("anything"), QuoteStatus.UNCHECKED)


class SurveyTest(unittest.TestCase):
    def test_keeps_rejects_and_summarises_the_rest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "61.json").write_text(json.dumps(profile_doc()))
            (directory / "62.json").write_text(json.dumps(profile_doc(app_id=62, access="nope")))
            survey = Survey.load(directory)
        self.assertEqual(list(survey.profiles), [61])
        self.assertIn("62.json", survey.rejected)
        self.assertEqual(survey.primary_auth(), {"oauth2": 1})
        self.assertEqual(survey.verdicts()["build_now"], 1)


class DisputeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.disputes = Disputes.load()

    def test_every_dispute_has_a_ruling_and_the_tally_covers_them_all(self) -> None:
        counted = sum(sum(bucket.values()) for bucket in self.disputes.tally().values())
        self.assertEqual(counted, len(self.disputes.items))

    def test_an_author_override_replaces_the_blind_check_and_is_labelled(self) -> None:
        podio_mcp = next(d for d in self.disputes.items if d.app == "Podio" and d.field is Field.MCP)
        self.assertIs(podio_mcp.winner, Winner.AGENT)
        self.assertIs(podio_mcp.decider, Decider.EVIDENCE_OVERRIDE)

    def test_the_live_data_loads_and_the_tally_covers_every_dispute(self) -> None:
        counted = sum(sum(bucket.values()) for bucket in self.disputes.tally().values())
        self.assertEqual(counted, len(self.disputes.items))


class DisputeFixtureTest(unittest.TestCase):
    def make_root(self, tmp: str, rulings: List[Dict[str, object]], decisions: List[Dict[str, object]]) -> Path:
        root = Path(tmp)
        (root / "runs" / "checks").mkdir(parents=True)
        (root / "data").mkdir()
        key = [
            {"item": 1, "app": "Attio", "field": "verdict", "kind": "changed", "A_is": "pass2"},
            {"item": 2, "app": "Aircall", "field": "verdict", "kind": "changed", "A_is": "pass1"},
            {"item": 3, "app": "Podio", "field": "mcp", "kind": "sample_miss", "A_is": "agent"},
        ]
        (root / "runs" / "checks" / "adjudication_key.json").write_text(json.dumps(key))
        (root / "runs" / "checks" / "adjudication_rulings_a.json").write_text(json.dumps(rulings))
        (root / "runs" / "checks" / "adjudication_rulings_b.json").write_text("[]")
        (root / "data" / "decisions.json").write_text(json.dumps(decisions))
        return root

    RULINGS = [{"item": 1, "ruling": "A"}, {"item": 2, "ruling": "A"}, {"item": 3, "ruling": "B"}]

    def test_a_ruling_resolves_against_which_side_was_shown_first(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            disputes = Disputes.load(self.make_root(tmp, self.RULINGS, []))
        winners = {d.item: d.winner for d in disputes.items}
        self.assertEqual(winners, {1: Winner.PASS2, 2: Winner.PASS1, 3: Winner.REFERENCE})

    def test_only_a_change_the_blind_check_did_not_back_needs_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            disputes = Disputes.load(self.make_root(tmp, self.RULINGS, []))
        self.assertEqual([d.app for d in disputes.items if d.needs_review], ["Aircall"])
        self.assertEqual(disputes.contested_fields(), {"Aircall": ["verdict"]})
        self.assertEqual(disputes.to_review(), 1)

    def test_a_recheck_resolves_a_contest_but_is_not_counted_as_a_person(self) -> None:
        decisions = [{"item": 2, "decision": "pass2", "by": "agent", "note": "why"}]
        with tempfile.TemporaryDirectory() as tmp:
            disputes = Disputes.load(self.make_root(tmp, self.RULINGS, decisions))
        aircall = disputes.items[1]
        self.assertIs(aircall.winner, Winner.PASS2)
        self.assertIs(aircall.decider, Decider.STRICT_RECHECK)
        self.assertEqual((disputes.contested_fields(), disputes.reviewed(), disputes.rechecked()), ({}, 0, 1))

    def test_a_decision_without_a_by_is_a_human_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            disputes = Disputes.load(self.make_root(tmp, self.RULINGS, [{"item": 2, "decision": "pass1"}]))
        self.assertIs(disputes.items[1].decider, Decider.HUMAN)
        self.assertEqual((disputes.reviewed(), disputes.rechecked()), (1, 0))

    def test_bad_inputs_are_refused_with_a_message(self) -> None:
        cases = [
            ([{"item": 1, "ruling": "A"}], [], "no ruling for items"),
            (self.RULINGS, [{"item": 9, "decision": "pass1"}], "not in the key"),
            (self.RULINGS, [{"item": 2, "decision": "agent"}], "not a possible winner"),
        ]
        for rulings, decisions, message in cases:
            with tempfile.TemporaryDirectory() as tmp, self.assertRaisesRegex(ValueError, message):
                Disputes.load(self.make_root(tmp, rulings, decisions))


class ChangesTest(unittest.TestCase):
    def test_lists_every_scored_field_a_later_pass_changed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            first, final = Path(tmp) / "pass1", Path(tmp) / "pass2"
            for directory, doc in ((first, profile_doc()), (final, profile_doc(access="paid_plan", auth_methods=["oauth2"]))):
                directory.mkdir()
                (directory / "61.json").write_text(json.dumps(doc))
            changes = Survey.load(final).changes_since(Survey.load(first))
        self.assertEqual(
            [(c["field"], c["before"], c["after"]) for c in changes],
            [("auth_methods", ["oauth2", "api_key"], ["oauth2"]), ("access", ["free_self_serve"], ["paid_plan"])],
        )

    def test_an_unchanged_pass_has_no_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "61.json").write_text(json.dumps(profile_doc()))
            survey = Survey.load(directory)
        self.assertEqual(survey.changes_since(survey), [])


class FetchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                code = {"/ok": 200, "/zipped": 200, "/gone": 404, "/blocked": 403, "/broken": 503}.get(self.path, 404)
                self.send_response(code)
                if self.path == "/zipped":
                    self.send_header("Content-Encoding", "gzip")
                self.end_headers()
                if self.path == "/zipped":
                    self.wfile.write(gzip.compress(b"<p>Send the key in the <code>x-api-key</code> header .</p>"))
                elif code == 200:
                    self.wfile.write(b"<p>Create an <b>API key</b> in settings</p>")

            def log_message(self, *args: object) -> None:
                pass

        cls.server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()

    def test_maps_each_outcome_to_a_status(self) -> None:
        self.assertIs(Page.fetch(self.base + "/ok").status, PageStatus.LIVE)
        self.assertIs(Page.fetch(self.base + "/gone").status, PageStatus.NOT_FOUND)
        self.assertIs(Page.fetch(self.base + "/blocked").status, PageStatus.REFUSED)
        self.assertIs(Page.fetch(self.base + "/broken").status, PageStatus.SERVER_ERROR)
        self.assertIs(Page.fetch("http://127.0.0.1:1/").status, PageStatus.UNREACHABLE)

    def test_a_compressed_page_is_read_and_tag_gaps_do_not_hide_a_quote(self) -> None:
        page = Page.fetch(self.base + "/zipped")
        self.assertIs(page.quote_status("Send the key in the x-api-key header."), QuoteStatus.FOUND)

    def test_an_empty_quote_is_never_found_here_or_in_the_sandbox_script(self) -> None:
        page = Page.fetch(self.base + "/ok")
        self.assertIs(page.quote_status(" ** "), QuoteStatus.UNCHECKED)
        answer = remote_check.Check.page((self.base + "/ok", ["", "API key", " ** "]))
        self.assertEqual(answer["found"], [False, True, False])

    def test_the_sandbox_script_reads_a_compressed_page(self) -> None:
        answer = remote_check.Check.page((self.base + "/zipped", ["x-api-key header."]))
        self.assertEqual((answer["code"], answer["found"]), (200, [True]))

    def test_finds_a_quote_on_a_fetched_page(self) -> None:
        page = Page.fetch(self.base + "/ok")
        self.assertIs(page.quote_status("create an API key in settings"), QuoteStatus.FOUND)
        self.assertIs(page.quote_status("no such sentence"), QuoteStatus.MISSING)

    def test_addresses_urllib_cannot_send_do_not_abort_the_run(self) -> None:
        self.assertIs(Page.fetch("http://[bad").status, PageStatus.UNREACHABLE)
        self.assertIs(Page.fetch("https://exämple.com/é").status, PageStatus.UNREACHABLE)

    def test_links_command_writes_one_entry_per_citation_with_page_and_quote_status(self) -> None:
        evidence = [{"field": f, "url": self.base + path, "quote": "API key"}
                    for f, path in (("auth_methods", "/ok"), ("access", "/ok"), ("api_styles", "/gone"), ("mcp", "/ok"))]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            directory = root / "runs" / "pass9"
            directory.mkdir(parents=True)
            (directory / "61.json").write_text(json.dumps(profile_doc(evidence=evidence)))
            out = io.StringIO()
            with mock.patch("research.__main__.ROOT", root), mock.patch.object(sys, "argv", ["research", "links", str(directory)]), \
                    contextlib.redirect_stdout(out):
                self.assertEqual(main(), 0)
            written = json.loads((root / "runs" / "checks" / "pass9_links.json").read_text())
        self.assertEqual([(e["field"], e["page"], e["quote"]) for e in written],
                         [("auth_methods", "live", "found"), ("access", "live", "found"),
                          ("api_styles", "not_found", "unchecked"), ("mcp", "live", "found")])
        self.assertIn('"citations": 4', out.getvalue())

    def test_a_scope_answer_counts_only_if_its_quote_is_found_here_or_in_the_sandbox(self) -> None:
        class Fake:
            def check_pages(self, pages):
                return [PageAnswer(200, tuple(quote == "found remotely" for quote in quotes)) for _, quotes in pages]

        def finding(app_id: int, quote: str, scope: Scope = Scope.ACCOUNT) -> ScopeFinding:
            return ScopeFinding(app_id, f"App{app_id}", scope, "why", self.base + "/ok", quote)

        findings = [finding(1, "create an API key"), finding(2, "found remotely"), finding(3, "nowhere"),
                    finding(4, "", Scope.UNCLEAR)]
        scopes = McpScopes(tuple(findings), McpScopes.verify(findings, Fake()))
        self.assertEqual(scopes.effective(), {1: Scope.ACCOUNT, 2: Scope.ACCOUNT, 3: Scope.UNCLEAR, 4: Scope.UNCLEAR})
        self.assertEqual(scopes.counts(), {"account": 2, "no_account": 0, "unclear": 2})
        self.assertEqual(scopes.unverified(), 1)

    def test_link_report_writes_one_entry_per_citation_and_fetches_each_url_once(self) -> None:
        cited = [{"field": f, "url": self.base + "/ok", "quote": "create an API key"}
                 for f in ("auth_methods", "access", "api_styles")]
        cited.append({"field": "mcp", "url": self.base + "/gone", "quote": "anything"})
        report = LinkReport.run([Profile.from_json(profile_doc(evidence=cited))])
        self.assertEqual(len(report.checks), 4)
        totals = report.totals()
        self.assertEqual(totals["verified"], 3)
        self.assertEqual(totals["pages"], {"live": 3, "not_found": 1})
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out" / "links.json"
            report.write(path)
            self.assertEqual(LinkReport.read(path), report)

    def test_a_page_cut_at_the_size_cap_cannot_prove_a_quote_missing(self) -> None:
        page = Page("https://x.io", PageStatus.LIVE, 200, "start", truncated=True)
        self.assertIs(page.quote_status("late text"), QuoteStatus.UNCHECKED)


class BoundaryTest(unittest.TestCase):
    def test_evidence_needs_an_ascii_web_address_with_a_host(self) -> None:
        for bad in ("ftp://x.io/a", "https://", "https://exämple.com/", "docs.x.io"):
            with self.assertRaises(ProfileError, msg=bad):
                Profile.from_json(profile_doc(evidence=[{"field": "mcp", "url": bad, "quote": "q"}]))

    def test_doc_reads_enums_and_text_or_names_the_bad_key(self) -> None:
        doc = Doc({"access": "paid_plan", "styles": ["rest", "soap"], "note": 5})
        self.assertIs(doc.enum(Access, "access"), Access.PAID_PLAN)
        self.assertEqual(len(doc.enums(ApiStyle, "styles")), 2)
        with self.assertRaisesRegex(ProfileError, "note"):
            doc.text("note")
        with self.assertRaisesRegex(ProfileError, "styles"):
            Doc({"styles": []}).enums(ApiStyle, "styles")

    def test_the_cited_fields_exclude_the_judgements(self) -> None:
        self.assertEqual(set(Field.cited()), set(Field) - {Field.VERDICT, Field.BLOCKER})

    def test_evidence_field_must_be_a_known_field(self) -> None:
        with self.assertRaisesRegex(ProfileError, "evidence field: 'mpc'"):
            Profile.from_json(profile_doc(evidence=[{"field": "mpc", "url": "https://x.io", "quote": "q"}]))

    def test_survey_lists_odd_files_instead_of_crashing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "61.json").write_text(json.dumps(profile_doc()))
            (directory / "notes.json").write_text(json.dumps(profile_doc()))
            (directory / "99.json").write_text(json.dumps(profile_doc()))
            (directory / "bin.json").write_bytes(b"\xff\xfe")
            survey = Survey.load(directory)
        self.assertEqual(list(survey.profiles), [61])
        self.assertEqual(set(survey.rejected), {"notes.json", "99.json", "bin.json"})

    def test_hand_check_values_are_checked_against_the_allowed_set(self) -> None:
        with self.assertRaisesRegex(HandCheckError, "not_a_mode"):
            HandCheck.from_json(hand_check_doc(mcp=["not_a_mode"]))


class SampleTest(unittest.TestCase):
    def test_the_seeded_draw_reproduces_the_hand_checked_apps(self) -> None:
        root = Path(__file__).resolve().parent.parent
        drawn = Sample.draw(root / "data" / "apps.csv")
        hand_checked = [row["app_id"] for row in json.loads((root / "data" / "handchecks.json").read_text())]
        self.assertEqual(len(drawn), 20)
        self.assertEqual(sorted(drawn), sorted(hand_checked))


class RemoteTest(unittest.TestCase):
    def test_the_sandbox_script_reads_pages_as_the_local_check_does(self) -> None:
        for text in ("Create an <b>API\u00a0key</b>", "Use `x-api-key` header ( see docs ) .", "It\u2019s \u201cOAuth\u201d \u2013 two  words &amp; more"):
            self.assertEqual(remote_check.Check.normalise(text), Page.normalise(text))
        page = "<p>keep</p><script>drop()</script><style>x{}</style>"
        self.assertEqual(remote_check.Check.readable(page), Page.readable(page))

    def test_answers_are_matched_to_citations_by_position_not_by_address(self) -> None:
        class Fake:
            def check_pages(self, pages):  # the real sandbox may redact an address, so only order is kept
                return [PageAnswer(200, (True,) * len(quotes)) for _, quotes in pages]

        evidence = [{"field": f, "url": "https://x.io/create-auth-token", "quote": "q"}
                    for f in ("auth_methods", "access", "api_styles", "mcp")]
        report = RemoteReport.run([Profile.from_json(profile_doc(evidence=evidence))], Fake())
        self.assertEqual([c.found for c in report.checks], [True] * 4)

    def test_compare_counts_agreement_and_refuses_reports_for_different_citations(self) -> None:
        def local(found: List[bool]) -> LinkReport:
            return LinkReport(tuple(
                LinkCheck(61, "GitHub", "mcp", "https://x.io", PageStatus.LIVE, 200,
                          QuoteStatus.FOUND if hit else QuoteStatus.MISSING) for hit in found))

        remote = RemoteReport(tuple(RemoteCheck(61, "https://x.io", "q", 200, hit) for hit in (True, True, False)))
        self.assertEqual(remote.compare(local([True, False, False])), {
            "citations": 3, "local_found": 1, "remote_found": 2, "both_found": 1, "only_local": 0, "only_remote": 1})
        with self.assertRaises(ValueError):
            remote.compare(local([True]))

    @staticmethod
    def fake_post(short: bool = False):
        """Stands in for Composio's HTTP API: opens a session, then runs the batch it is sent."""
        def post(api_key, url, body):
            if url.endswith("/session"):
                return {"session_id": "s1"}
            payload = re.search(r"echo (\S+) \| base64 -d \| python3", body["arguments"]["command"]).group(1)
            pages = json.loads(base64.b64decode(payload))
            answers = [{"code": 200, "found": [True] * (len(quotes) - short)} for _, quotes in pages]
            return {"error": None, "data": {"stdout": json.dumps(answers)}}
        return post

    def remote_root(self, tmp: str) -> Path:
        root = Path(tmp)
        directory = root / "runs" / "pass9"
        directory.mkdir(parents=True)
        (directory / "61.json").write_text(json.dumps(profile_doc()))
        return root

    def run_remote(self, root: Path, post) -> int:
        out = io.StringIO()
        with mock.patch("research.__main__.ROOT", root), mock.patch.object(Sandbox, "_post", staticmethod(post)), \
                mock.patch.dict(os.environ, {"COMPOSIO_API_KEY": "k"}), \
                mock.patch.object(sys, "argv", ["research", "remote", str(root / "runs" / "pass9")]), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            return main()

    def test_the_remote_command_compares_the_sandbox_with_the_local_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self.remote_root(tmp)
            (root / "runs" / "checks").mkdir()
            citations = [LinkCheck(61, "GitHub", f, "https://docs.github.com/rest", PageStatus.LIVE, 200, QuoteStatus.FOUND)
                         for f in ("auth_methods", "access", "api_styles", "mcp")]
            LinkReport(tuple(citations)).write(root / "runs" / "checks" / "pass9_links.json")
            self.assertEqual(self.run_remote(root, self.fake_post()), 0)
            written = RemoteReport.read(root / "runs" / "checks" / "pass9_remote_links.json")
        self.assertEqual([c.found for c in written.checks], [True] * 4)

    def test_a_missing_local_report_stops_the_command_before_the_sandbox_is_used(self) -> None:
        def refuse(*args):
            raise AssertionError("the sandbox must not be opened")

        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(self.run_remote(self.remote_root(tmp), refuse), 1)

    def test_a_sandbox_that_checks_fewer_quotes_than_it_was_sent_is_an_error(self) -> None:
        profile = Profile.from_json(profile_doc())
        with mock.patch.object(Sandbox, "_post", staticmethod(self.fake_post(short=True))):
            with self.assertRaisesRegex(CatalogError, "checked 3 of 4 quotes"):
                RemoteReport.run([profile], Sandbox("k", "s1"))

    def test_the_sandbox_needs_a_key_and_reports_a_failed_command(self) -> None:
        with self.assertRaisesRegex(CatalogError, "COMPOSIO_API_KEY"):
            Sandbox.open("")
        with mock.patch.object(Sandbox, "_post", return_value={"error": "boom", "data": {}}):
            with self.assertRaisesRegex(CatalogError, "boom"):
                Sandbox("key", "session").bash("true")


class ScopeFileTest(unittest.TestCase):
    def test_findings_are_read_from_one_file_per_app_and_bad_values_are_refused(self) -> None:
        doc = {"app_id": 5, "app": "X", "scope": "account", "reason": "r", "url": "https://x.io", "quote": "q"}
        self.assertIs(ScopeFinding.from_json(doc).scope, Scope.ACCOUNT)
        with self.assertRaisesRegex(ProfileError, "scope"):
            ScopeFinding.from_json(dict(doc, scope="everything"))
        with self.assertRaisesRegex(ProfileError, "needs a quote"):
            ScopeFinding.from_json(dict(doc, quote=" ** "))
        with tempfile.TemporaryDirectory() as tmp:
            directory, checks = Path(tmp) / "scope", Path(tmp) / "checks.json"
            directory.mkdir()
            with self.assertRaisesRegex(ProfileError, "no scope files"):
                McpScopes.load(directory, checks)
            (directory / "5.json").write_text(json.dumps(doc))
            checks.write_text(json.dumps([ScopeCheck(5, QuoteStatus.FOUND, False).to_json()]))
            self.assertEqual(McpScopes.load(directory, checks).effective(), {5: Scope.ACCOUNT})


class BrowserReportTest(unittest.TestCase):
    def combine(self, local: List[QuoteStatus], remote: List[bool], browser: List[bool]) -> Dict[str, int]:
        urls = [f"https://x.io/{n}" for n in range(len(local))]
        report = LinkReport(tuple(LinkCheck(1, "X", "mcp", u, PageStatus.LIVE, 200, q) for u, q in zip(urls, local)))
        sandbox = RemoteReport(tuple(RemoteCheck(1, u, f"q{n}", 200, hit) for n, (u, hit) in enumerate(zip(urls, remote))))
        browsed = BrowserReport(tuple(BrowserCheck(1, u, f"q{n}", hit) for n, (u, hit) in enumerate(zip(urls, browser))))
        return browsed.combine(report, sandbox)

    def test_a_citation_counts_once_and_the_browser_only_adds_what_the_others_missed(self) -> None:
        found, missing = QuoteStatus.FOUND, QuoteStatus.MISSING
        counts = self.combine([found, missing, missing, missing], [True, True, False, False], [True, True, True, False])
        self.assertEqual(counts, {"citations": 4, "confirmed": 3, "browser_added": 1})

    def test_reports_for_different_citations_are_refused(self) -> None:
        local = LinkReport((LinkCheck(1, "X", "mcp", "https://x.io/a", PageStatus.LIVE, 200, QuoteStatus.FOUND),))
        sandbox = RemoteReport((RemoteCheck(1, "https://x.io/b", "q", 200, True),))
        with self.assertRaises(ValueError):
            BrowserReport(()).combine(local, sandbox)


class IndependentReviewTest(unittest.TestCase):
    def write(self, directory: Path, rows: Dict[str, object]) -> None:
        for name, rows_ in rows.items():
            (directory / name).write_text(json.dumps(rows_))

    def test_a_ruling_counts_only_when_its_quote_was_found_and_maps_back_to_whose_answer_it_backs(self) -> None:
        key = [{"item": 1, "app_id": 5, "app": "X", "field": "mcp", "A_is": "independent"},
               {"item": 2, "app_id": 5, "app": "X", "field": "access", "A_is": "pipeline"},
               {"item": 3, "app_id": 6, "app": "Y", "field": "mcp", "A_is": "pipeline"}]
        ruling = {"source": "https://x.io", "quote": "q", "note": "n"}
        rulings = [dict(ruling, item=1, ruling="A"), dict(ruling, item=2, ruling="A"), dict(ruling, item=3, ruling="B")]
        quotes = [{"item": 1, "local": "found", "remote": False}, {"item": 2, "local": "missing", "remote": True},
                  {"item": 3, "local": "missing", "remote": False}]
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            self.write(directory, {"independent_key.json": key, "independent_rulings_0.json": rulings,
                                   "independent_quotes.json": quotes})
            review = IndependentReview.load(directory)
        self.assertEqual([i.winner.value for i in review.items], ["reference", "agent", "unclear"])
        self.assertEqual(review.tally(), {"reference": 1, "agent": 1, "unclear": 1})

    def test_rulings_must_cover_exactly_the_keyed_items(self) -> None:
        key = [{"item": 1, "app_id": 5, "app": "X", "field": "mcp", "A_is": "pipeline"}]
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            self.write(directory, {"independent_key.json": key, "independent_rulings_0.json": []})
            with self.assertRaisesRegex(ProfileError, "rulings cover"):
                IndependentReview.load(directory)


class CatalogTest(unittest.TestCase):
    CATALOG = ComposioCatalog("2026-11-23", (
        Toolkit("hubspot", "HubSpot", 100, ("OAUTH2",)),
        Toolkit("help_scout", "Help Scout", 30, ("OAUTH2",)),
        Toolkit("googleads", "Google Ads", 40, ("OAUTH2",)),
        Toolkit("zoho", "Zoho", 80, ("OAUTH2",)),
        Toolkit("netlify_mcp", "Netlify MCP", 20, ()),
        Toolkit("notebook_lm", "NotebookLM", 10, ("OAUTH2",)),
    ))

    def test_matches_by_name_slug_and_a_reviewed_alias(self) -> None:
        for app, slug in (("HubSpot", "hubspot"), ("Help Scout", "help_scout"), ("Google Ads", "googleads"),
                          ("NotebookLM", "notebook_lm"), ("Zoho CRM", "zoho")):
            match = self.CATALOG.lookup(app)
            self.assertIs(match.coverage, Coverage.NATIVE, app)
            self.assertEqual(match.toolkit.slug, slug)

    def test_an_mcp_only_toolkit_is_not_counted_as_native(self) -> None:
        self.assertIs(self.CATALOG.lookup("Netlify").coverage, Coverage.MCP_ONLY)

    def test_an_app_with_no_toolkit_is_none_and_the_key_is_required(self) -> None:
        self.assertIs(self.CATALOG.lookup("Vonage").coverage, Coverage.NONE)
        with self.assertRaisesRegex(CatalogError, "COMPOSIO_API_KEY"):
            ComposioCatalog.fetch("")

    def test_composio_auth_is_read_as_the_briefs_methods_and_only_extras_are_reported(self) -> None:
        toolkit = Toolkit("x", "X", 1, ("OAUTH2", "DCR_OAUTH", "API_KEY", "SAML"))
        self.assertEqual(toolkit.auth_methods(), {AuthMethod.OAUTH2, AuthMethod.API_KEY, AuthMethod.OTHER})
        match = Match(Coverage.NATIVE, toolkit)
        self.assertEqual(match.auth_not_in((AuthMethod.OAUTH2,)), ["api_key", "other"])
        self.assertEqual(match.auth_not_in((AuthMethod.OAUTH2, AuthMethod.BEARER_TOKEN)), ["other"])
        self.assertEqual(match.auth_not_in((AuthMethod.OAUTH2, AuthMethod.API_KEY, AuthMethod.OTHER, AuthMethod.BASIC)), [])
        self.assertEqual(Match(Coverage.NONE, None).auth_not_in(()), [])

    def test_the_snapshot_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "catalog.json"
            self.CATALOG.write(path)
            self.assertEqual(ComposioCatalog.read(path), self.CATALOG)


class CaseStudyTest(unittest.TestCase):
    def test_the_page_data_covers_every_app_and_agrees_with_the_disputes(self) -> None:
        study = CaseStudy.build()
        data = study.to_json()
        verification = data["verification"]
        self.assertEqual(len(data["apps"]), 100)
        self.assertEqual(verification["reference_leniency"]["apps"], 20)
        self.assertEqual(verification["to_review"], study.disputes.to_review())
        flagged = {app["app"] for app in data["apps"] if app["contested"]}
        self.assertEqual(flagged, set(study.disputes.contested_fields()))

    def test_render_writes_the_page_with_the_data_inlined(self) -> None:
        study = CaseStudy.build()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "site").mkdir()
            shutil.copytree(ROOT / "site_src", root / "site_src")
            page = study.render(root)
            self.assertIn('"apps"', page.read_text())
            self.assertTrue((root / "site" / "data.json").exists())


class CommandTest(unittest.TestCase):
    def test_a_missing_directory_is_an_error_not_zero_valid(self) -> None:
        self.assertEqual(self.run_main("validate", "/no/such/directory"), 1)

    def run_main(self, *argv: str) -> int:
        with mock.patch.object(sys, "argv", ["research", *argv]), contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            return main()

    def test_validate_exits_nonzero_only_when_a_profile_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "61.json").write_text(json.dumps(profile_doc()))
            self.assertEqual(self.run_main("validate", str(directory)), 0)
            (directory / "62.json").write_text(json.dumps(profile_doc(app_id=62, access="nope")))
            self.assertEqual(self.run_main("validate", str(directory)), 1)

    def test_score_can_skip_apps_that_have_no_valid_profile_and_says_which(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "pass"
            directory.mkdir()
            (directory / "61.json").write_text(json.dumps(profile_doc()))
            checks = Path(tmp) / "checks.json"
            checks.write_text(json.dumps([hand_check_doc(), hand_check_doc(app_id=99, app="Gone")]))
            out = io.StringIO()
            with mock.patch.object(sys, "argv", ["research", "score", str(directory), str(checks), "--skip-missing"]), \
                    contextlib.redirect_stdout(out):
                self.assertEqual(main(), 0)
            self.assertIn("skipped 1 apps with no valid profile: Gone", out.getvalue())
            self.assertEqual(self.run_main("score", str(directory), str(checks)), 1)

    def test_score_reports_a_hand_check_with_no_profile_as_an_error_not_a_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            checks = Path(tmp).parent / "scope_checks_for_test.json"
            self.addCleanup(checks.unlink)
            checks.write_text(json.dumps([hand_check_doc()]))
            self.assertEqual(self.run_main("score", tmp, str(checks)), 1)

    def test_site_command_writes_the_page_data_under_the_root_and_prints_the_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("site_src", "data", "runs"):
                shutil.copytree(ROOT / name, root / name)
            (root / "site").mkdir()
            out = io.StringIO()
            with mock.patch("research.__main__.ROOT", root), mock.patch.object(sys, "argv", ["research", "site"]), \
                    contextlib.redirect_stdout(out):
                self.assertEqual(main(), 0)
            data = json.loads((root / "site" / "data.json").read_text())
            self.assertTrue((root / "site" / "index.html").exists())
        self.assertEqual(len(data["apps"]), 100)
        self.assertIn("(100 apps)", out.getvalue())


if __name__ == "__main__":
    unittest.main()
