# Brief: independent check of an app, read in a browser

You are checking what is true about each app below, from the vendor's own pages, without knowing
what anyone else concluded. Do not open anything under `runs/`, `data/`, `site/` or `docs/`. They
hold other people's answers and reading them would spoil the check.

Read `agent/prompts/research.md` for the field definitions and allowed values only. Then, for each app,
open the vendor's developer docs, pricing or sign-up pages and, if it has one, its MCP page, in a real
browser (the BrowserOS tools: load them with ToolSearch, then navigate, read, snapshot). A browser
renders pages that a plain fetch cannot, so use it for pages that come back empty. Third-party
articles do not count.

Answer these six fields exactly as research.md defines them:
`auth_methods` (a list), `access`, `api_styles` (a list), `mcp`, `verdict`, `blocker`.

Write one file per app to the output path you are given:

```json
{"app_id": 0, "app": "", "auth_methods": ["oauth2"], "access": ["free_self_serve"], "api_styles": ["rest"],
 "mcp": ["none"], "verdict": ["build_now"], "blocker": ["none"],
 "sources": ["https://vendor page you read"], "note": "anything the docs leave open"}
```

Single-value fields are written as one-item lists. Where the docs honestly support two readings,
list both and say why in `note`. Use only values from the allowed sets. If a page would not load
even in the browser, say which one in `note` and answer only what you could read. Do not guess.
