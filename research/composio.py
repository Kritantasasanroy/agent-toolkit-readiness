"""Which of the apps already have a Composio toolkit, read from Composio's own catalog.

The catalog comes from Composio's toolkits API. A snapshot is committed so the page and the
checks rebuild without a key; `python3 -m research composio` refreshes it and needs the key
in COMPOSIO_API_KEY, which is never written to disk.
"""

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Tuple


class CatalogError(ValueError):
    pass


class Coverage(Enum):
    NATIVE = "native"      # a toolkit built for the app
    MCP_ONLY = "mcp_only"  # only an MCP-server toolkit (slug ends in _mcp)
    NONE = "none"


@dataclass(frozen=True)
class Toolkit:
    slug: str
    name: str
    tools: int
    auth: Tuple[str, ...]

    @classmethod
    def from_api(cls, doc: Mapping[str, object]) -> "Toolkit":
        meta = doc.get("meta") or {}
        return cls(
            slug=str(doc["slug"]),
            name=str(doc["name"]),
            tools=int(meta.get("tools_count", 0)) if isinstance(meta, dict) else 0,
            auth=tuple(str(scheme) for scheme in doc.get("auth_schemes") or ()),
        )

    def to_json(self) -> Dict[str, object]:
        return {"slug": self.slug, "name": self.name, "tools": self.tools, "auth": list(self.auth)}


@dataclass(frozen=True)
class Match:
    coverage: Coverage
    toolkit: Optional[Toolkit]

    def to_json(self) -> Dict[str, object]:
        return {
            "coverage": self.coverage.value,
            "slug": self.toolkit.slug if self.toolkit else "",
            "tools": self.toolkit.tools if self.toolkit else 0,
        }


@dataclass(frozen=True)
class ComposioCatalog:
    API = "https://backend.composio.dev/api/v3/toolkits"
    PAGE_SIZE = 1000
    TIMEOUT_SECONDS = 30
    # Names that differ from the toolkit's slug and were checked against its description.
    ALIASES = {
        "Zoho CRM": "zoho",              # the Zoho suite toolkit, which includes the CRM
        "WhatsApp Business": "whatsapp",  # "WhatsApp Business API"
        "Monday.com": "monday",
        "MongoDB Atlas": "mongodb",       # "Administer MongoDB Atlas organizations ..."
    }

    fetched: str
    toolkits: Tuple[Toolkit, ...]

    @staticmethod
    def _key(text: str) -> str:
        return re.sub(r"[^a-z0-9]", "", re.sub(r"\(.*?\)", "", text.lower()))

    @classmethod
    def fetch(cls, api_key: str) -> "ComposioCatalog":
        if not api_key:
            raise CatalogError("set COMPOSIO_API_KEY to fetch the catalog")
        toolkits: List[Toolkit] = []
        cursor = ""
        while True:
            url = f"{cls.API}?limit={cls.PAGE_SIZE}" + (f"&cursor={cursor}" if cursor else "")
            request = urllib.request.Request(url, headers={"x-api-key": api_key})
            try:
                with urllib.request.urlopen(request, timeout=cls.TIMEOUT_SECONDS) as response:
                    page = json.loads(response.read())
            except urllib.error.HTTPError as err:
                raise CatalogError(f"Composio returned HTTP {err.code}") from err
            except (OSError, ValueError) as err:
                raise CatalogError(f"could not read the Composio catalog: {err}") from err
            toolkits.extend(Toolkit.from_api(item) for item in page["items"])
            cursor = page.get("next_cursor") or ""
            if not cursor:
                return cls(date.today().isoformat(), tuple(toolkits))

    @classmethod
    def read(cls, path: Path) -> "ComposioCatalog":
        doc = json.loads(path.read_text())
        return cls(doc["fetched"], tuple(
            Toolkit(t["slug"], t["name"], t["tools"], tuple(t["auth"])) for t in doc["toolkits"]
        ))

    def write(self, path: Path) -> None:
        doc = {"fetched": self.fetched, "toolkits": [t.to_json() for t in self.toolkits]}
        path.write_text(json.dumps(doc, separators=(",", ":")))

    def lookup(self, app_name: str) -> Match:
        """A native toolkit if the app has one, else an MCP-only toolkit, else none."""
        by_slug = {t.slug: t for t in self.toolkits}
        by_key: Dict[str, Toolkit] = {}
        for toolkit in self.toolkits:
            by_key.setdefault(self._key(toolkit.slug), toolkit)
            by_key.setdefault(self._key(toolkit.name), toolkit)
        alias = self.ALIASES.get(app_name)
        native = by_slug.get(alias) if alias else by_key.get(self._key(app_name))
        if native is not None:
            return Match(Coverage.NATIVE, native)
        mcp = by_key.get(self._key(alias or app_name) + "mcp")
        return Match(Coverage.MCP_ONLY, mcp) if mcp is not None else Match(Coverage.NONE, None)
