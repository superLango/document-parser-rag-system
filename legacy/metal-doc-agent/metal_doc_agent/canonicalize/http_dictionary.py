"""HTTP business-dictionary adapter (M1.8 live integration).

Supports two common shapes without changing engine code:

* one dictionary endpoint returning ``{"version", "entries": [...]}``;
* split item/method endpoints returning lists or wrapped lists.

Field names differ across business systems, so the adapter accepts a small set
of common aliases (``item_code``/``project_code``/``business_code`` etc.) and
normalizes status values before they reach matching.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any

from ..contracts import BusinessDictionary, BusinessDictionaryEntry
from .dictionary import DictionaryAdapter

ITEM_CODE_FIELDS = ("business_code", "item_code", "project_code", "code", "id")
ITEM_NAME_FIELDS = (
    "business_name",
    "item_name",
    "project_name",
    "detection_item_name",
    "name",
    "title",
)
METHOD_CODE_FIELDS = ("business_code", "method_code", "code", "id")
METHOD_NAME_FIELDS = (
    "business_name",
    "method_name",
    "test_method_name",
    "name",
    "title",
)
FAMILY_FIELDS = ("family", "item_family", "category", "category_name")
ALIAS_FIELDS = ("aliases", "alias", "synonyms", "other_names", "alias_names")
STANDARD_FIELDS = ("standard_no", "standard", "std_no", "method_standard")
STATUS_FIELDS = ("status", "state", "enabled", "is_active")
FACET_FIELDS = ("facets", "dimensions", "attributes")
VERSION_FIELDS = ("version", "dictionary_version", "data_version")
ACTIVE_VALUES = {"active", "enabled", "valid", "1", "true", "on", "正常", "启用"}
INACTIVE_VALUES = {"inactive", "disabled", "invalid", "0", "false", "off", "停用"}
PENDING_VALUES = {"pending", "draft", "review", "audit", "待确认", "待审核"}


class BusinessApiError(RuntimeError):
    """Raised when the business API is unreachable or returns an invalid body."""


class HttpDictionaryAdapter(DictionaryAdapter):
    source = "api"

    def __init__(
        self,
        base_url: str,
        *,
        api_key: str | None = None,
        items_path: str = "/items",
        methods_path: str = "/methods",
        dictionary_path: str | None = None,
        timeout: float = 15.0,
        auth_header: str = "Authorization",
        auth_prefix: str = "Bearer ",
        headers: dict[str, str] | None = None,
        retries: int = 1,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.items_path = items_path
        self.methods_path = methods_path
        self.dictionary_path = dictionary_path
        self.timeout = timeout
        self.auth_header = auth_header
        self.auth_prefix = auth_prefix
        self.headers = dict(headers or {})
        self.retries = max(0, retries)

    def load(self) -> BusinessDictionary:
        if self.dictionary_path:
            payload, headers = self._get(self.dictionary_path)
            entries = _entries_from_payload(payload, None)
            version = _version(payload, headers)
            return BusinessDictionary(
                version=version,
                source="api",
                entries=[_coerce_entry(item, None) for item in entries],
            )

        item_payload, item_headers = self._get(self.items_path)
        method_payload, method_headers = self._get(self.methods_path)
        item_entries = _entries_from_payload(item_payload, "item")
        method_entries = _entries_from_payload(method_payload, "method")
        version = _version(item_payload, item_headers) or _version(
            method_payload, method_headers
        )
        entries = [
            _coerce_entry(item, "item") for item in item_entries
        ] + [
            _coerce_entry(item, "method") for item in method_entries
        ]
        return BusinessDictionary(version=version, source="api", entries=entries)

    def _get(self, path: str) -> tuple[Any, dict[str, str]]:
        url = path if path.startswith(("http://", "https://")) else self.base_url + path
        headers = {"Accept": "application/json", **self.headers}
        if self.api_key:
            headers[self.auth_header] = f"{self.auth_prefix}{self.api_key}"
        last_error: Exception | None = None
        for _ in range(self.retries + 1):
            request = urllib.request.Request(url, headers=headers, method="GET")
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    body = response.read().decode("utf-8")
                    return json.loads(body), dict(response.headers)
            except urllib.error.HTTPError as error:
                snippet = error.read().decode("utf-8", errors="replace")[:300]
                last_error = BusinessApiError(
                    f"{url} returned HTTP {error.code}: {snippet}"
                )
                if error.code < 500:
                    break
            except (urllib.error.URLError, TimeoutError, OSError) as error:
                last_error = BusinessApiError(f"{url} unreachable: {error}")
            except json.JSONDecodeError as error:
                last_error = BusinessApiError(f"{url} returned invalid JSON: {error}")
                break
        raise last_error or BusinessApiError(f"{url} request failed")


def _entries_from_payload(payload: Any, entry_type: str | None) -> list[dict]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        raise BusinessApiError("business API payload must be an object or list")
    for key in ("entries", "items", "methods", "data", "records", "rows", "list"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    if entry_type and isinstance(payload.get(entry_type), list):
        return [item for item in payload[entry_type] if isinstance(item, dict)]
    raise BusinessApiError("business API payload has no entries/items/methods list")


def _version(payload: Any, headers: dict[str, str]) -> str:
    if isinstance(payload, dict):
        for key in VERSION_FIELDS:
            value = payload.get(key)
            if value:
                return str(value)
    for key, value in headers.items():
        if key.lower() in {"x-dictionary-version", "x-data-version", "etag"} and value:
            return value.strip('"')
    return "api"


def _coerce_entry(raw: dict, entry_type: str | None) -> BusinessDictionaryEntry:
    declared = str(raw.get("type") or raw.get("entry_type") or "").lower()
    resolved_type = entry_type or ("method" if declared in {"method", "test_method"} else "item")
    code_fields = METHOD_CODE_FIELDS if resolved_type == "method" else ITEM_CODE_FIELDS
    name_fields = METHOD_NAME_FIELDS if resolved_type == "method" else ITEM_NAME_FIELDS
    code = _first(raw, code_fields)
    name = _first(raw, name_fields)
    if not code or not name:
        raise BusinessApiError(
            f"entry missing code/name for type {resolved_type}: {raw}"
        )
    return BusinessDictionaryEntry(
        business_code=str(code).strip(),
        business_name=str(name).strip(),
        type=resolved_type,
        family=_optional_text(_first(raw, FAMILY_FIELDS)),
        facets=_facets(_first(raw, FACET_FIELDS)),
        aliases=_aliases(_first(raw, ALIAS_FIELDS)),
        standard_no=_optional_text(_first(raw, STANDARD_FIELDS)),
        status=_status(_first(raw, STATUS_FIELDS)),
        version=_optional_text(_first(raw, VERSION_FIELDS)),
    )


def _first(raw: dict, fields: tuple[str, ...]) -> Any:
    for field in fields:
        if field in raw and raw[field] not in (None, "", []):
            return raw[field]
    return None


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _aliases(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [
            part.strip()
            for part in re.split(r"[,，、;；|]", value)
            if part.strip()
        ]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _facets(value: Any) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, list[str]] = {}
    for key, raw in value.items():
        if isinstance(raw, list):
            result[str(key)] = [str(item).strip() for item in raw if str(item).strip()]
        elif raw not in (None, ""):
            result[str(key)] = [str(raw).strip()]
    return result


def _status(value: Any) -> str:
    if value is None:
        return "active"
    if isinstance(value, bool):
        return "active" if value else "inactive"
    text = str(value).strip().lower()
    if text in ACTIVE_VALUES:
        return "active"
    if text in INACTIVE_VALUES:
        return "inactive"
    if text in PENDING_VALUES:
        return "pending"
    return "active"
