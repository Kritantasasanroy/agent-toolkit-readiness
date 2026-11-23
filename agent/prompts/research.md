# Research brief: app integration profile

You are profiling one app to decide whether it can become an agent toolkit: a set of
tools an AI agent calls on behalf of a user who connects their own account.

Work only from what you can read today. Use web search to find the vendor's developer
docs, then open the pages and read them. Prefer the vendor's own docs over blogs. Never
fill a field from memory alone: if you could not find a page that says it, say so in
`notes` and lower `confidence`.

## Output

Write exactly one JSON object per app, nothing else, to the file path you were given.

```json
{
  "app_id": 1,
  "app": "Salesforce",
  "category": "CRM and Sales",
  "summary": "Cloud CRM for managing leads, accounts, opportunities and service cases.",
  "auth_methods": ["oauth2"],
  "access": "free_self_serve",
  "access_note": "Free Developer Edition org; connected apps created in Setup.",
  "api_styles": ["rest", "graphql"],
  "api_breadth": "broad",
  "mcp": "official",
  "mcp_url": "https://...",
  "verdict": "build_now",
  "blocker": "none",
  "blocker_note": "",
  "evidence": [
    {"field": "auth_methods", "url": "https://...", "quote": "exact sentence copied from the page"}
  ],
  "confidence": "high",
  "notes": ""
}
```

## Field rules

Use only the values listed. Lowercase, exactly as written.

`summary`: one plain sentence, what the product does for its customer.

`auth_methods` (one or more, primary first)
- `oauth2`: OAuth 2.0 authorization code or client credentials flow.
- `api_key`: a static key or personal/private token the user generates in settings.
- `basic`: username and password, or key sent as HTTP Basic.
- `bearer_token`: a bot or access token issued some other way (e.g. a Telegram bot token,
  a long-lived system-user token).
- `other`: HMAC request signing, JWT/service account, session login, mTLS.
- `none`: no auth because there is no hosted API (e.g. a local CLI).

`access`: the gate a single developer hits to get credentials that work on their own account.
- `free_self_serve`: sign up free (free plan, developer account or sandbox) and create keys yourself.
- `free_trial`: only possible during a time-limited trial.
- `paid_plan`: API access needs a paid tier.
- `admin_approval`: a workspace admin must approve or install, or the vendor must approve a
  developer token or app before it works at all.
- `partner_gated`: partner program, contact sales, or customer-only docs.
- `no_public_api`: no documented public API exists.

`api_styles` (one or more): `rest`, `graphql`, `soap`, `rpc` (JSON-RPC/gRPC/websocket),
`sdk_only` (no wire API documented, only a library), `cli` (local command line tool), `none`.

`api_breadth`: `broad` (most of the product is reachable, dozens of resources), `moderate`
(core objects only), `narrow` (a handful of endpoints), `none`.

`mcp`: `official` (published or hosted by the vendor), `community` (a third-party server with
real usage, e.g. on GitHub or an MCP registry), `none` (you searched and found nothing).
Give `mcp_url` for anything but `none`.

`verdict`: could this be an agent toolkit that any user can connect today?
- `build_now`: self-serve credentials and a usable API. No outreach needed.
- `build_with_caveat`: buildable, but with a real limit (paid tier for the end user, app
  review before going multi-tenant, narrow API, rate limits).
- `needs_outreach`: a partner program, sales contact or vendor approval stands in the way.
- `not_feasible`: no API to wrap, or only unofficial access.

`blocker`: the single biggest obstacle. `none`, `partner_program`, `paid_plan`,
`app_review` (OAuth app or developer token needs vendor review before other users can
connect), `admin_install`, `no_public_api`, `narrow_api`, `region_or_kyc`, `unofficial_only`.

`evidence`: at least one item each for `auth_methods`, `access`, `api_styles` and `mcp`
(for `mcp: none`, cite the docs or registry page you checked). `quote` must be copied
word for word from the page at `url`, short (under 200 characters), and must actually
support the claim. A checker will open every URL and look for the quote.

`confidence`: `high` if every field is backed by the vendor's own docs, `medium` if one
field leans on a third-party source or inference, `low` if you could not find docs.

`notes`: anything a reviewer should know: conflicting sources, pages that would not load,
assumptions you made.
