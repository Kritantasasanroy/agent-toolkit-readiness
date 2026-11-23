# Review brief: second pass on an app profile

A first-pass agent wrote a profile for this app under `agent/prompts/research.md`. Your job
is to find what it got wrong. Assume every field is unproven until you have read a page that
proves it. Read the research brief first; its field rules and allowed values still apply.

You are given:
- the first-pass profile (`runs/pass1/<app_id>.json`)
- the link check for its evidence (`runs/checks/pass1_links.json`, entries with this app_id):
  `page` says whether the URL loaded, `quote` says whether the quoted text was found on it.

## What to do

1. For every evidence item whose page did not load or whose quote was `missing`, open the
   page yourself. If the quote is not on the page, replace it with a sentence that is, or
   find a better page. A quote you cannot find word for word does not count as evidence.
2. Re-check each field against the vendor's own docs, in this order of risk:
   `access` (is there really a free path, or is it trial, paid or partner only?), `mcp`
   (is the server really the vendor's, and does it exist?), `blocker` and `verdict` (do they
   follow from access and auth under the brief's definitions?), then `auth_methods` and
   `api_styles`.
3. Prefer pages that render as plain HTML (API references, help-centre articles, GitHub
   READMEs) over JavaScript-heavy marketing pages, so the quote can be checked by a script.
4. Keep what is right. Change only what you can show is wrong or unsupported.

## Output

Write the full corrected profile, in the same format as the brief, to
`runs/pass2/<app_id>.json`, with one extra key:

```json
"review": [
  {"field": "access", "from": "free_self_serve", "to": "paid_plan",
   "reason": "Pricing page: API access starts on the Business plan."}
]
```

`review` is an empty list when nothing changed. Set `confidence` to what the evidence now
supports, not what the first pass claimed.
