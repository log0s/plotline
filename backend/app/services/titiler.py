"""Request shaping shared by every Titiler caller (tile proxy, warmup, preview renderer)."""

from __future__ import annotations

from typing import Any

from app.config import Settings


def titiler_params(settings: Settings, params: dict[str, Any]) -> dict[str, Any]:
    """Return ``params`` with the Titiler access token appended when one is configured.

    With no token configured the dict is returned unchanged, so a Titiler that
    does not yet enforce a token sees exactly the request it saw before.
    """
    if not settings.titiler_access_token:
        return params
    return {**params, "access_token": settings.titiler_access_token}
