# App toolkit readiness: 100 apps

Research on whether 100 apps can become agent toolkits today: how each one authenticates,
whether a developer can get credentials without talking to anyone, what the API looks like,
whether an MCP server exists, and what blocks the ones that can't be built yet.

## How it works

```
data/apps.csv ──> research agent ──> runs/pass1/<id>.json
                       │                     │
                       │        validate (schema + evidence rules)
                       │        links    (fetch every cited page, look for the quote)
                       │                     │
                       └──── review agent <──┘ ──> runs/pass2/<id>.json
                                                         │
                     data/handchecks.json ──> score ──> accuracy per pass
                                                         │
                                              site ──> site/index.html, site/data.json
```

- `agent/prompts/research.md` is the brief the research agent follows: the fields, the
  allowed values and the evidence rules. `agent/prompts/verify.md` is the brief for the
  second pass, which gets the first profile and the link-check results and has to prove or
  fix every field.
- Both passes ran as parallel Claude Sonnet 5.5 sub-agents (10 to 15 apps each) with web
  search and page fetch, orchestrated from a Claude Code session. Pass 2 differs from pass 1
  in its inputs, not its model: it receives the first profile and the link-check results,
  and has to prove or fix every field from the raw page text.
- `research/` is the checking code. It is plain Python 3.9 with no dependencies, so anyone
  can rerun the checks without an API key.
- `data/handchecks.json` holds reference answers for 20 apps, two per category, drawn with
  a fixed seed (`research/sample.py`, seed 2026). Each lists the vendor pages it came from. Where the
  docs honestly support two readings, both are accepted and the note says why.

## Run it

```bash
python3 -m research validate runs/pass1          # schema and evidence rules
python3 -m research links runs/pass1             # writes runs/checks/pass1_links.json
python3 -m research score runs/pass1 data/handchecks.json
python3 -m research validate runs/pass2
python3 -m research links runs/pass2
python3 -m research score runs/pass2 data/handchecks.json
COMPOSIO_API_KEY=... python3 -m research composio   # refreshes the Composio catalog snapshot (optional)
python3 -m research site                         # builds site/index.html and site/data.json
python3 -m unittest discover -s tests -t .
```

No Python setup on your machine? Open the repo's Actions tab, pick "Verify the research" and
press Run workflow. It runs the tests, validates all 100 pass-2 profiles, scores both passes and
rebuilds the page data on GitHub's runners, with no API key. (The research agents themselves ran
inside a Claude Code session and are not triggered from the page.)

To research a new app, give a Claude agent with web access `agent/prompts/research.md`,
the app's name and hint, and the output path `runs/pass1/<id>.json`, then run the steps
above. The checks don't care which model wrote the file, only whether it holds up.

## Layout

| Path | What it is |
| --- | --- |
| `data/apps.csv` | The 100 apps from the brief |
| `data/handchecks.json` | Reference answers for the 20-app sample |
| `data/composio_toolkits.json` | Snapshot of Composio's toolkit catalog, used to mark which apps already have a toolkit |
| `data/decisions.json`, `data/overrides.json` | How each contested answer was settled, with the reasoning |
| `agent/prompts/` | Research and review briefs |
| `runs/pass1/`, `runs/pass2/` | One profile per app per pass |
| `runs/checks/` | Link-check results per pass |
| `research/` | Validation, link checking, scoring, site build |
| `site/` | The published page, its data and `llms.txt` for agents |
| `site_src/` | Page template and copy; `python3 -m research site` builds `site/index.html` from them |
| `.github/workflows/` | The runnable check trigger and the Pages deploy |
| `docs/design.md` | The data model behind the code |
