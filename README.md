# App toolkit readiness: 100 apps

Live case study: https://kritantasasanroy.github.io/agent-toolkit-readiness/

For each of the 100 apps on the list I worked out how it authenticates, whether a developer can
get credentials without asking anyone, how broad the API is, whether an MCP server exists, and
what blocks the apps that cannot be built yet. The case study has the table, the patterns and
the accuracy checks. This repo has the agent briefs, the raw results and the code that checks them.

## How it works

```
data/apps.csv ──> research agent ──> runs/pass1/<id>.json
                       │                     │
                       │        validate (allowed values, evidence rules)
                       │        links    (fetch every cited page, look for the quote)
                       │                     │
                       └──── review agent <──┘ ──> runs/pass2/<id>.json
                                                         │
                     data/handchecks.json ──> score ──> accuracy per pass
                                                         │
                                              site ──> site/index.html, site/data.json
```

- `agent/prompts/research.md` is the brief the research agent follows. It fixes the fields, the
  allowed values and the evidence rules. `agent/prompts/verify.md` is the brief for the second
  pass, which receives the first profile and the link-check results and has to prove or fix every field.
- Both passes ran as parallel research agents with web search and page fetch, ten to fifteen
  apps each. Pass 2 differs from pass 1 in its inputs, not its model.
- `research/` holds the checking code. It is plain Python 3.9 with no dependencies, so the
  checks run without an API key.
- `data/handchecks.json` has reference answers for 20 apps, two per category, drawn with a fixed
  seed (`research/sample.py`, seed 2026). Each lists the vendor pages it came from. Where the
  docs support two readings, both are accepted and the note says why.
- `agent/prompts/mcp_scope.md` is a third brief. For each official MCP server it records whether the
  server can reach a customer's account or only serves docs, public data or tooling, with a quote.
- Composio is used as a check, not as the research engine. `research composio` reads its toolkits
  API for coverage and a second opinion on auth methods, and `research remote` re-runs the
  evidence check inside a Composio sandbox. Both read `COMPOSIO_API_KEY` from the environment.
  The key is never written to disk.

## Run it

```bash
python3 -m research validate runs/pass1          # allowed values and evidence rules
python3 -m research links runs/pass1             # writes runs/checks/pass1_links.json
python3 -m research score runs/pass1 data/handchecks.json
python3 -m research validate runs/pass2
python3 -m research links runs/pass2
python3 -m research score runs/pass2 data/handchecks.json
COMPOSIO_API_KEY=... python3 -m research composio            # refresh the Composio catalog snapshot (optional)
COMPOSIO_API_KEY=... python3 -m research remote runs/pass2   # re-run the evidence check in a Composio sandbox (optional)
COMPOSIO_API_KEY=... python3 -m research scope               # check the quotes behind the MCP scope answers (optional)
python3 -m research site                         # builds site/index.html and site/data.json
python3 -m unittest discover -s tests -t .
```

No Python on your machine? Open the Actions tab, pick "Verify the research" and press Run workflow.
It runs the tests, validates all 100 final profiles, scores both passes and rebuilds the page data
on GitHub's runners, with no API key. The research agents themselves are not triggered from the page.

To research a new app, give an agent with web access `agent/prompts/research.md`, the app's name
and a hint, and the output path `runs/pass1/<id>.json`. Then run the steps above. The checks do
not care which model wrote the file, only whether it holds up.

## What it got wrong

The case study lists every miss. The ones to know about: the reference sample was written with AI
help, so it is a sanity check and not independent proof. The "official MCP" count includes
servers that serve only docs, public data or tooling. The page splits them, and the split comes from agent reading with quote checks. Copper's API access during a trial is still open. Several vendor
sites refuse automated requests, so some quotes could not be confirmed.
