"""Strip credentials out of text before it reaches a log line or a DB row.

httpx renders the full request URL into ``str(HTTPStatusError)``, GDAL echoes
signed blob URLs into Titiler error bodies, and connection strings carry a
password — so every place an exception, request or response becomes a string
is a place a secret can leak. Rather than fixing each call site, the log
pipeline (``logging_config.py``) and the task-row error sinks
(``services/imagery.py``) run everything through ``redact``. Written for a
log sink that is already external.
"""

from __future__ import annotations

import re
from collections.abc import MutableMapping
from typing import Any

# Query parameters whose values are credentials: the Census API key, every
# Azure SAS field (sig/se/sp/st/sr/sv/skoid/… — ``se`` and ``st`` are only
# expiry/start times, but a full SAS is reconstructable from the set, so the
# whole family goes), Titiler's access token, and generic token names.
_SECRET_PARAMS = (
    "key",
    "sig",
    "se",
    "sp",
    "st",
    "sr",
    "sv",
    "skoid",
    "sktid",
    "skt",
    "ske",
    "sks",
    "skv",
    "access_token",
    "token",
    "api_key",
    "apikey",
    "app_token",
)

_PARAM_RE = re.compile(
    r"(?<![A-Za-z0-9_])(" + "|".join(_SECRET_PARAMS) + r")=([^&\s'\"<>)\]]+)",
    re.IGNORECASE,
)
# scheme://user:password@host  →  scheme://user:***@host
_URL_CREDENTIAL_RE = re.compile(r"(\b[a-z][a-z0-9+.-]*://[^/\s:@]+:)[^@\s/]+@", re.IGNORECASE)

_MASK = "***"


def redact(text: str) -> str:
    """Return ``text`` with credential-bearing query values and URL passwords masked."""
    text = _PARAM_RE.sub(lambda m: f"{m.group(1)}={_MASK}", text)
    return _URL_CREDENTIAL_RE.sub(lambda m: f"{m.group(1)}{_MASK}@", text)


def redact_value(value: Any) -> Any:
    """``redact`` applied through strings, lists, tuples and dicts; other types pass through."""
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {k: redact_value(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return type(value)(redact_value(v) for v in value)
    return value


def redact_event_dict(
    _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """structlog processor: scrub every string in the event, including rendered exceptions."""
    for key, value in event_dict.items():
        if key.startswith("_"):
            continue
        event_dict[key] = redact_value(value)
    return event_dict
