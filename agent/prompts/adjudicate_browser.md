# Adjudication brief, read in a browser

Two answers exist for one field of one app. You do not know where either came from. Decide which
one the vendor's own public documentation supports today.

Read `agent/prompts/adjudicate.md` first for the field meanings and the output shape, and follow it.
The one change: open the vendor's pages in a real browser (the BrowserOS tools, loaded with
ToolSearch), not with curl, because many docs sites only render in a browser. Open your own tab,
wait a few seconds for the page to render, and close the tab when you are done. Use vendor pages
only. Do not open anything under `runs/`, `data/`, `site/` or `docs/`.

Each ruling needs a `quote` copied word for word from the vendor page you cite. It will be searched
for on that page, and a ruling whose quote cannot be found counts as `unclear`.
