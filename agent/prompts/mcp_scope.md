# Brief: what can an official MCP server actually do?

For each app you are given, the vendor publishes an MCP server. Decide what kind it is.

Scopes (use exactly one):
- `account`: the server lets an agent read or change a customer's own data in the product (records, messages, tickets, orders, files, deployments) after that customer signs in or supplies a key.
- `no_account`: the server only searches or serves documentation, API references, public data, or developer tooling such as code generation. It has no access to a customer's own account data.
- `unclear`: you could not tell from the vendor's own pages.

How to work:
1. Open the app's `mcp_url` and the vendor's own MCP documentation. Use only vendor pages (docs, help centre, the vendor's GitHub organisation). Third-party directories do not count.
2. Find the list of tools or the description of what the server does. Look for verbs that act on account data (create, update, list your, send) against verbs that only fetch documentation (search docs, get API reference).
3. If a vendor ships two servers, one of each kind, answer `account` and say so in the reason.
4. Copy one short quote, word for word, from a vendor page that supports your answer. The quote will be searched for on the page, so do not paraphrase it.

Write one JSON file per app to the path you are given, in this shape:

```json
{"app_id": 0, "app": "", "scope": "account", "reason": "one or two sentences", "url": "vendor page you read", "quote": "word for word from that page"}
```

If a page will not load, say so in the reason and use `unclear`. Do not guess.
