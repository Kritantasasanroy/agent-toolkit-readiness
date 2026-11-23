# Design: app integration research

## What this is

A research pipeline that profiles 100 apps for one question: can each become an agent
toolkit today, and if not, what stands in the way. An agent writes a profile per app with
cited evidence, scripts check the evidence, a second agent pass corrects what the checks
flag, and every answer the passes disagreed on is settled from the vendor's docs and, where
it matters, by a person.

## Concepts

| Concept | Definition | Kind |
| --- | --- | --- |
| App | A product from the research set, with its name, category and a hint where to look. | row in `data/apps.csv` |
| Profile | What one research pass concluded about one app's integration surface, with the evidence behind it. | entity |
| Evidence | A quote on a public page that supports one cited field of a profile. | value |
| Survey | Every profile produced by one research pass, read as a whole. | entity |
| Page | A fetched evidence page: its address, whether it loaded, and its readable text. | value |
| LinkCheck | Whether one citation's page loaded and still contains the quoted text. | value |
| LinkReport | Every LinkCheck for one pass, with totals. | entity |
| HandCheck | A person's answer for one app's six scored fields, taken from the vendor's docs. | entity |
| Comparison | One field of one app: what the agent said, what the hand check accepts, and whether they match. | value |
| Scorecard | How a survey's answers compare with the hand checks, field by field. | value |
| Dispute | One answer two sources disagreed on, and who settled it from the docs. | entity |
| ComposioCatalog | Composio's toolkit catalog at one date, used to say whether an app already has a native toolkit, an MCP-only one, or none, and which auth methods that toolkit offers beyond the ones the research lists. | value |
| Doc | One JSON object from a pass, read with the checks the brief's contract needs (`enum`, `enums`, `text`). | value |
| RemoteReport | The evidence check run a second time in a Composio sandbox: one RemoteCheck per citation, compared with the local LinkReport. | entity |
| Sandbox | A Composio tool-router session with a remote shell, used to run `research/remote_check.py`. | value |
| McpScopes | What each official MCP server can reach (a customer's account, or only docs, public data and tooling), one finding per app with a quote that is checked on the page. | entity |
| Disputes | Every dispute, with the tally, the contested apps and the review count. | entity |
| CaseStudy | Everything the published page shows, assembled from the saved passes and checks, plus the page it renders. | value |
| Sample | The reference sample: two apps per category, drawn with seed 2026 so anyone can reproduce it. | value |

Enums carry every fixed set: `AuthMethod`, `Access`, `ApiStyle`, `ApiBreadth`, `Mcp`,
`Verdict`, `Blocker`, `Confidence`, `Field` (the fields scored and cited), `PageStatus`,
`QuoteStatus`, and for disputes `Kind`, `Side`, `Ruling`, `Winner`, `Decider`, and `Coverage` for catalog matches. Behaviour sits on the type it derives from (`Field.allowed`, `Field.cited`, `Ruling.resolve`, `Page.normalise`, `PageStatus.for_code`, `HandCheck.leniency`).

Everything is general to integration research except the verdict rules, which encode what
matters to a toolkit platform: a user must be able to connect their own account without
the platform negotiating access first.

## Model

```
App
 └─ Profile            one per app per pass, keyed by app_id
      └─ Evidence      one or more per profile, each tied to a Field

Survey                 all profiles from one pass (runs/pass1, runs/pass2)
LinkReport             one LinkCheck per citation in a Survey
RemoteReport           the same citations checked from a Composio sandbox
 └─ LinkCheck          built from a Page fetched once per distinct URL
Scorecard              Survey compared against HandChecks on the sampled apps

Disputes               every disagreement, shown to a blind check as two shuffled options
 └─ Dispute            a Kind (pass 2 changed pass 1, or the agent missed the reference),
                       the Side that was option A, the blind Ruling, and the final Winner
```

- `Profile` refuses to load if any enum value is unknown, if a cited field has no evidence,
  if an evidence address is not an ASCII web address with a host, or if `mcp_url` is empty
  while `mcp` claims a server. That is the brief's contract with the agent.
- `Survey` owns the aggregate questions (auth mix, access by category, blocker ranking) and
  `changes_since`, which lists every field a later pass changed. It rejects a file whose name
  is not its `app_id` (the file name is the key, so an id cannot repeat) and lists it instead of failing.
  A missing or empty directory is an error.
- A field matches a hand check as follows. For the two list fields a correct first answer
  plus any subset of the accepted values counts, so omissions are never penalised and the
  score measures precision, not completeness. For single-value fields the answer must be
  exactly one value from the accepted set, and the set can hold more than one reading.
  `leniency` reports how many single-value answers accept several.
- `Disputes` owns the contested rule. A change needs review when the blind check did not
  back pass 2. It stays contested until a person decides it.

## Dispute lifecycle

```
raised           pass 2 changed a field, or an agent answer missed the reference
  -> blind check a fresh agent sees two shuffled, unlabelled options and rules A, B,
                  both, neither or unclear from the vendor's docs
  -> override     optional: a correction recorded with its evidence
                  (data/overrides.json, shown as "live test"; the file says how it was made)
  -> decision     optional: pass1, pass2 or both, written to data/decisions.json with a note.
                  Without a "by" it is a review by hand; with "by": "agent" it is a re-read
                  of the docs, shown separately and never counted as a hand review
```

The later layer wins. A dispute is never edited or deleted; the page shows who decided it.

## CRUD

Profiles are written once per pass by an agent and never edited by code. A correction is a
new profile in the next pass, so pass 1 stays available for scoring. Hand checks are written
by a person and read by the scorer. Disputes are created from the key and rulings files,
read by the page builder, and never deleted. Decisions and overrides are append-only files
read at load time. Nothing is deleted.

## Decisions

- Two passes on disk instead of editing in place: the change is measured, not claimed.
- Link checking is separate from the agent: a model that wrote a quote should not be the one
  that confirms it exists.
- Disputes are judged blind and then overridable by evidence or a person, because the blind
  check was shown to be wrong at least once (Podio's MCP server).
- Composio's catalog is a second source for auth methods that no research agent wrote. A
  difference is reported, not corrected: Composio often offers fewer methods than the vendor.
- The sandbox redacts anything that looks like a secret, including addresses such as
  `.../create-auth-token/`, so its answers are matched to citations by position.
- An MCP scope answer counts only if its quote is found on the cited page, here or in the sandbox. Otherwise it is shown as unclear.
- The auth cross-check treats an API key and a bearer token as the same credential, because vendors and Composio label it either way.
- Standard library only, so the checks run anywhere with Python 3.9.
- The committed site must equal a fresh build (checked in CI), so the build output carries no date.
- Numbers on the page are filled from the data when it loads. The conclusions beside them
  (for example "two auth methods cover the list") are the author's reading of today's data and
  must be rechecked if the data changes.
