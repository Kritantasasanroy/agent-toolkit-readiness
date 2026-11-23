"""An app's integration profile, as written by one research pass."""

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Dict, List, Mapping, Sequence, Tuple, Type, TypeVar
from urllib.parse import urlsplit


class AuthMethod(Enum):
    OAUTH2 = "oauth2"
    API_KEY = "api_key"
    BASIC = "basic"
    BEARER_TOKEN = "bearer_token"
    OTHER = "other"
    NONE = "none"


class Access(Enum):
    FREE_SELF_SERVE = "free_self_serve"
    FREE_TRIAL = "free_trial"
    PAID_PLAN = "paid_plan"
    ADMIN_APPROVAL = "admin_approval"
    PARTNER_GATED = "partner_gated"
    NO_PUBLIC_API = "no_public_api"

    @property
    def is_self_serve(self) -> bool:
        return self in (Access.FREE_SELF_SERVE, Access.FREE_TRIAL)


class ApiStyle(Enum):
    REST = "rest"
    GRAPHQL = "graphql"
    SOAP = "soap"
    RPC = "rpc"
    SDK_ONLY = "sdk_only"
    CLI = "cli"
    NONE = "none"


class ApiBreadth(Enum):
    BROAD = "broad"
    MODERATE = "moderate"
    NARROW = "narrow"
    NONE = "none"


class Mcp(Enum):
    OFFICIAL = "official"
    COMMUNITY = "community"
    NONE = "none"


class Verdict(Enum):
    BUILD_NOW = "build_now"
    BUILD_WITH_CAVEAT = "build_with_caveat"
    NEEDS_OUTREACH = "needs_outreach"
    NOT_FEASIBLE = "not_feasible"


class Blocker(Enum):
    NONE = "none"
    PARTNER_PROGRAM = "partner_program"
    PAID_PLAN = "paid_plan"
    APP_REVIEW = "app_review"
    ADMIN_INSTALL = "admin_install"
    NO_PUBLIC_API = "no_public_api"
    NARROW_API = "narrow_api"
    REGION_OR_KYC = "region_or_kyc"
    UNOFFICIAL_ONLY = "unofficial_only"


class Confidence(Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Field(Enum):
    """Profile fields that carry evidence and are scored for accuracy."""

    AUTH_METHODS = "auth_methods"
    ACCESS = "access"
    API_STYLES = "api_styles"
    MCP = "mcp"
    VERDICT = "verdict"
    BLOCKER = "blocker"

    @property
    def is_list(self) -> bool:
        """Fields where a profile may name several values."""
        return self in (Field.AUTH_METHODS, Field.API_STYLES)

    @property
    def allowed(self) -> Type[Enum]:
        return {
            Field.AUTH_METHODS: AuthMethod, Field.ACCESS: Access, Field.API_STYLES: ApiStyle,
            Field.MCP: Mcp, Field.VERDICT: Verdict, Field.BLOCKER: Blocker,
        }[self]

    @classmethod
    def cited(cls) -> Tuple["Field", ...]:
        """The fields the brief requires a citation for; verdict and blocker are judgements."""
        return (cls.AUTH_METHODS, cls.ACCESS, cls.API_STYLES, cls.MCP)


class ProfileError(ValueError):
    pass


E = TypeVar("E", bound=Enum)


class Doc:
    """One JSON object from a pass, read with the checks the brief's contract needs."""

    def __init__(self, raw: Mapping[str, object]) -> None:
        self.raw = raw

    def enum(self, kind: Type[E], key: str) -> E:
        return self._coerce(kind, key, self.raw.get(key))

    @staticmethod
    def _coerce(kind: Type[E], key: str, value: object) -> E:
        try:
            return kind(value)
        except ValueError:
            allowed = ", ".join(member.value for member in kind)
            raise ProfileError(f"{key}: {value!r} is not one of {allowed}") from None

    def enums(self, kind: Type[E], key: str) -> Tuple[E, ...]:
        value = self.raw.get(key)
        if not isinstance(value, list) or not value:
            raise ProfileError(f"{key}: expected a non-empty list, got {value!r}")
        return tuple(self._coerce(kind, key, item) for item in value)

    def text(self, key: str) -> str:
        value = self.raw.get(key, "")
        if not isinstance(value, str):
            raise ProfileError(f"{key}: expected text, got {value!r}")
        return value


@dataclass(frozen=True)
class Evidence:
    field: Field
    url: str
    quote: str

    @classmethod
    def from_json(cls, doc: object) -> "Evidence":
        if not isinstance(doc, dict):
            raise ProfileError(f"evidence: expected an object, got {doc!r}")
        fields = Doc(doc)
        try:
            evidence = cls(fields.enum(Field, "field"), fields.text("url"), fields.text("quote"))
        except ProfileError as err:
            raise ProfileError(f"evidence {err}") from err
        if not evidence.is_fetchable():
            raise ProfileError(f"evidence: {evidence.url!r} is not an ASCII web address")
        return evidence

    def is_fetchable(self) -> bool:
        """True for an http(s) address a plain fetch can send: ASCII, with a host."""
        parts = urlsplit(self.url)
        return parts.scheme in ("http", "https") and bool(parts.hostname) and self.url.isascii()

    def to_json(self) -> Dict[str, str]:
        return {"field": self.field.value, "url": self.url, "quote": self.quote}


@dataclass(frozen=True)
class Profile:
    app_id: int
    app: str
    category: str
    summary: str
    auth_methods: Tuple[AuthMethod, ...]
    access: Access
    access_note: str
    api_styles: Tuple[ApiStyle, ...]
    api_breadth: ApiBreadth
    mcp: Mcp
    mcp_url: str
    verdict: Verdict
    blocker: Blocker
    blocker_note: str
    evidence: Tuple[Evidence, ...]
    confidence: Confidence
    notes: str

    def __post_init__(self) -> None:
        cited = {item.field for item in self.evidence}
        missing = [field.value for field in Field.cited() if field not in cited]
        if missing:
            raise ProfileError(f"no evidence for {', '.join(missing)}")
        if self.mcp is not Mcp.NONE and not self.mcp_url:
            raise ProfileError(f"mcp is {self.mcp.value} but mcp_url is empty")

    @classmethod
    def from_json(cls, doc: Mapping[str, object]) -> "Profile":
        app_id = doc.get("app_id")
        if not isinstance(app_id, int):
            raise ProfileError(f"app_id: expected a number, got {app_id!r}")
        evidence = doc.get("evidence")
        if not isinstance(evidence, list):
            raise ProfileError(f"evidence: expected a list, got {evidence!r}")
        fields = Doc(doc)
        return cls(
            app_id=app_id,
            app=fields.text("app"),
            category=fields.text("category"),
            summary=fields.text("summary"),
            auth_methods=fields.enums(AuthMethod, "auth_methods"),
            access=fields.enum(Access, "access"),
            access_note=fields.text("access_note"),
            api_styles=fields.enums(ApiStyle, "api_styles"),
            api_breadth=fields.enum(ApiBreadth, "api_breadth"),
            mcp=fields.enum(Mcp, "mcp"),
            mcp_url=fields.text("mcp_url"),
            verdict=fields.enum(Verdict, "verdict"),
            blocker=fields.enum(Blocker, "blocker"),
            blocker_note=fields.text("blocker_note"),
            evidence=tuple(Evidence.from_json(item) for item in evidence),
            confidence=fields.enum(Confidence, "confidence"),
            notes=fields.text("notes"),
        )

    @classmethod
    def read(cls, path: Path) -> "Profile":
        try:
            doc = json.loads(path.read_text())
        except (json.JSONDecodeError, UnicodeDecodeError) as err:
            raise ProfileError(f"not valid JSON: {err}") from err
        if not isinstance(doc, dict):
            raise ProfileError("expected a JSON object")
        return cls.from_json(doc)

    def answer(self, field: Field) -> List[str]:
        """The profile's answer for a scored field, as the brief's string values."""
        value = getattr(self, field.value)
        members: Sequence[Enum] = value if isinstance(value, tuple) else (value,)
        return [member.value for member in members]

    def to_json(self) -> Dict[str, object]:
        return {
            "app_id": self.app_id,
            "app": self.app,
            "category": self.category,
            "summary": self.summary,
            "auth_methods": self.answer(Field.AUTH_METHODS),
            "access": self.access.value,
            "access_note": self.access_note,
            "api_styles": self.answer(Field.API_STYLES),
            "api_breadth": self.api_breadth.value,
            "mcp": self.mcp.value,
            "mcp_url": self.mcp_url,
            "verdict": self.verdict.value,
            "blocker": self.blocker.value,
            "blocker_note": self.blocker_note,
            "evidence": [item.to_json() for item in self.evidence],
            "confidence": self.confidence.value,
            "notes": self.notes,
        }
