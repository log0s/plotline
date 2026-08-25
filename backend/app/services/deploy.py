"""What the running deployment reports about itself.

The re-queue scripts gate on this. A heal is only as good as the deploy
behind it — re-queuing runs selection against whatever code the worker is
running — so ``requeue_parcels.py`` refuses to queue unless the deployed
SHA is the one the operator vouched for, and ``revalidate_landsat.py``
uses the same answer to skip parcels a previous run already swept under
that deploy.

Both fields come from ``/api/v1/health``, which reads them from the
``GIT_SHA`` / ``BUILT_AT`` build args baked into the image
(``Dockerfile.fly:39-42``). ``built`` is therefore the **image build**
time, stamped by CI at ``docker build`` (``deploy.yml:119``), not the
moment the machine started serving it. The gap is the rest of the CI job,
minutes rather than hours — see ``fetch_deployed_version`` for what that
costs a caller using it as a cutoff.
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
from pydantic import BaseModel


class DeployedVersion(BaseModel):
    """Build identity of the deployment currently answering health checks."""

    sha: str
    built: datetime | None


def fetch_deployed_version(api_url: str, *, timeout: float = 10.0) -> DeployedVersion:
    """Read ``version`` from the running API's health endpoint.

    Raises ``RuntimeError`` with an operator-readable message on anything
    that leaves the SHA unknown — an unreachable endpoint and a
    ``sha: "unknown"`` are both refusals, never a pass.

    ``built`` is ``None`` when the image carries no build stamp or one that
    will not parse; a caller using it as a time cutoff must decide what to
    do about that rather than silently treating it as the epoch. It is the
    build time, so it *precedes* the deploy: work done in the gap between
    build and rollout ran against the previous code while carrying a
    timestamp after this one.
    """
    url = f"{api_url.rstrip('/')}/api/v1/health"
    try:
        response = httpx.get(url, timeout=timeout)
    except httpx.RequestError as exc:
        raise RuntimeError(f"could not reach {url}: {exc}") from exc

    # 503 means a dependency is degraded; the body still carries the version.
    if response.status_code not in (200, 503):
        raise RuntimeError(f"{url} returned HTTP {response.status_code}")

    try:
        version = response.json()["version"]
        sha = version["sha"]
    except (ValueError, KeyError, TypeError) as exc:
        raise RuntimeError(f"{url} returned no version.sha field: {exc}") from exc

    if not isinstance(sha, str) or not sha or sha == "unknown":
        raise RuntimeError(f"{url} reports version.sha as {sha!r}")

    return DeployedVersion(sha=sha, built=_parse_built(version.get("built")))


def _parse_built(raw: object) -> datetime | None:
    if not isinstance(raw, str) or not raw or raw == "unknown":
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
