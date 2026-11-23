# Adjudication brief: settle a disputed answer from the docs

Two answers exist for one field of one app. You do not know where either came from. Decide
which one the vendor's own public documentation supports today.

## Field meanings

- `auth_methods`: how an end user's account is connected. `oauth2`, `api_key` (a key or personal
  token the user generates), `basic`, `bearer_token` (a bot or system token issued some other
  way), `other`, `none`.
- `access`: the gate a single developer hits to get working credentials. `free_self_serve`
  (free plan or developer account, creates keys alone), `free_trial` (only during a trial),
  `paid_plan`, `admin_approval` (admin or vendor approval needed), `partner_gated` (partner
  program or contact sales), `no_public_api`.
- `api_styles`: `rest`, `graphql`, `soap`, `rpc` (JSON-RPC, gRPC, websocket), `sdk_only`, `cli`, `none`.
- `mcp`: `official` (published or hosted by the vendor), `community` (third-party server),
  `none` (nothing found).
- `verdict`: `build_now`, `build_with_caveat`, `needs_outreach`, `not_feasible`.
- `blocker`: `none`, `partner_program`, `paid_plan`, `app_review`, `admin_install`,
  `no_public_api`, `narrow_api`, `region_or_kyc`, `unofficial_only`.

For `verdict` and `blocker`, judge from what the docs say about access, auth and approval for a
developer who wants other users to connect their own accounts.

## How

Open the vendor's docs with Bash (`curl -sL -A "Mozilla/5.0" <url>`; strip tags with python3 if
needed) or WebSearch/WebFetch. Prefer the vendor's own pages. A third-party page is not enough
on its own. Spend at most a few minutes per item.

## Output

For each item write one object, and save the full list to the output path you were given:

```json
{"item": 3, "ruling": "A", "source": "https://...", "quote": "short quote copied from the page", "note": "one line"}
```

`ruling` is `A`, `B`, `both` (the docs support both readings), `neither` (the docs support
something else; say what in `note`), or `unclear` (you could not find a vendor page that settles
it). Never guess: use `unclear`.
