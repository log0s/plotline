#!/usr/bin/env python3
"""Re-queue full timelines for the parcel ids given on the command line.

The general heal path. A parcel loses years to a transient upstream — a
signing-rate burst, a Census timeout — and the task still reports
``complete``, so backfill will never retry it (M4). Until per-year failures
are persisted, healing means re-running the whole pipeline for the parcels
an audit identified, and there has been a fresh set of those after every
incident. This script takes ids rather than deriving them, so it does not
need a new heuristic each time.

Parcels with a request already in flight are skipped and logged; the batch
continues, so re-running is safe.

Deployment gate
---------------
Re-queuing re-runs scene selection against whatever code the worker is
currently running, so a heal is only as good as the deploy behind it. The
imagery point filter tests each STAC item's *bbox envelope* rather than its
real footprint (``stac.py``), which admits granules whose footprint excludes
the address — so a re-queue against an un-fixed deploy re-selects the same
wrong granules and heals the parcel straight back into the defect.

To make the ordering mechanical rather than a thing the operator has to
remember, the script fetches ``/api/v1/health`` from the running API before
touching the database and reads ``version.sha`` — the SHA baked into the
deployed image. It then refuses to queue anything unless one of:

* ``--require-sha <prefix>`` matches the deployed SHA. The operator passes
  the SHA of the deploy that carries the geometry fix. This is a prefix
  match against what prod reports; it does *not* walk commit history, so
  passing a SHA that merely contains the fix in its ancestry is the
  operator's judgement, not something the script verifies.
* ``--skip-deploy-check`` is passed, which logs a warning naming what was
  skipped and proceeds anyway.

The health URL defaults to ``api_internal_url`` from settings (correct when
running via ``docker compose exec api``); ``--api-url`` overrides it. A
health endpoint that cannot be reached, or that reports ``sha`` as
``unknown``, is a refusal — not a pass.

Note on the entry point: this uses ``_create_queued_request`` rather than
``get_or_create_timeline_request``, matching ``revalidate_landsat.py`` and
``requeue_empty_property.py``. get_or_create deliberately *reuses* a
``complete`` request so a second visitor gets an instant answer — and a
damaged parcel's latest request is always complete, which is precisely the
case this script exists to re-run. It still goes through the service, so
the one-in-flight-per-parcel index is a skip rather than a crash that kills
the rest of the batch.

The gate runs for ``--dry-run`` too, so a dry run tells you whether the real
run would be allowed.

Usage (API + worker must be running):
    docker compose exec api python scripts/requeue_parcels.py \
        --require-sha <sha> --dry-run <id> [<id> ...]
    docker compose exec api python scripts/requeue_parcels.py \
        --require-sha <sha> <id> [<id> ...]
"""

from __future__ import annotations

import argparse
import sys
import uuid

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.db import SessionLocal
from app.models.parcels import Parcel
from app.services import imagery as imagery_service

logger = structlog.get_logger(__name__)

_WHY = (
    "re-queueing through the un-fixed imagery point filter re-selects the same "
    "wrong granules, healing the parcel back into the defect"
)


def _fetch_deployed_sha(api_url: str) -> str:
    """Return ``version.sha`` from the running API's health endpoint.

    Raises ``RuntimeError`` with an operator-readable message on anything
    that leaves the SHA unknown.
    """
    url = f"{api_url.rstrip('/')}/api/v1/health"
    try:
        response = httpx.get(url, timeout=10.0)
    except httpx.RequestError as exc:
        raise RuntimeError(f"could not reach {url}: {exc}") from exc

    # 503 means a dependency is degraded; the body still carries the version.
    if response.status_code not in (200, 503):
        raise RuntimeError(f"{url} returned HTTP {response.status_code}")

    try:
        sha = response.json()["version"]["sha"]
    except (ValueError, KeyError, TypeError) as exc:
        raise RuntimeError(f"{url} returned no version.sha field: {exc}") from exc

    if not isinstance(sha, str) or not sha or sha == "unknown":
        raise RuntimeError(f"{url} reports version.sha as {sha!r}")
    return sha


def _refuse(deployed: str, required: str | None) -> None:
    print("REFUSING to re-queue — deployment gate failed.", file=sys.stderr)
    print(f"  prod is running: {deployed}", file=sys.stderr)
    print(f"  required:        {required or '(none given)'}", file=sys.stderr)
    print(f"  why: {_WHY}.", file=sys.stderr)
    print(
        "  Pass --require-sha <prefix> matching a deploy that carries the "
        "geometry fix, or --skip-deploy-check to override.",
        file=sys.stderr,
    )
    sys.exit(1)


def _check_deploy_gate(api_url: str, require_sha: str | None, skip: bool) -> None:
    """Exit nonzero unless the deployed SHA is vouched for, or the gate is skipped."""
    if skip:
        logger.warning(
            "deploy_check_skipped",
            skipped="verification that the deployed API carries the imagery "
            "geometry fix (point-in-footprint instead of point-in-bbox)",
            danger=_WHY,
        )
        return

    try:
        deployed = _fetch_deployed_sha(api_url)
    except RuntimeError as exc:
        _refuse(f"unknown — {exc}", require_sha)
        return

    if require_sha and deployed.lower().startswith(require_sha.lower()):
        print(f"Deploy gate passed — prod is running {deployed}.")
        return

    _refuse(deployed, require_sha)


def _known_parcels(parcel_ids: list[uuid.UUID]) -> set[uuid.UUID]:
    with SessionLocal() as db:
        rows = db.execute(select(Parcel.id).where(Parcel.id.in_(parcel_ids))).scalars().all()
    return set(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Re-queue timelines for specific parcels")
    parser.add_argument("parcel_ids", nargs="+", help="Parcel UUIDs to re-queue")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List what would be queued without queuing anything",
    )
    parser.add_argument(
        "--api-url",
        default=get_settings().api_internal_url,
        help="Base URL of the running API to read /api/v1/health from",
    )
    parser.add_argument(
        "--require-sha",
        help="Git SHA prefix the deployed API must report before re-queuing",
    )
    parser.add_argument(
        "--skip-deploy-check",
        action="store_true",
        help="Re-queue without verifying the deployed SHA (logs a warning)",
    )
    args = parser.parse_args()

    _check_deploy_gate(args.api_url, args.require_sha, args.skip_deploy_check)

    try:
        parcel_ids = [uuid.UUID(raw) for raw in args.parcel_ids]
    except ValueError as exc:
        parser.error(f"not a parcel UUID: {exc}")

    known = _known_parcels(parcel_ids)
    unknown = [pid for pid in parcel_ids if pid not in known]
    for pid in unknown:
        print(f"  skipped {pid} — no such parcel")

    targets = [pid for pid in parcel_ids if pid in known]
    if not targets:
        print("Nothing to do.")
        return

    print(f"Re-queuing {len(targets)} parcel(s).")

    if args.dry_run:
        for pid in targets:
            print(f"  would re-queue: {pid}")
        return

    queued = 0
    skipped = len(unknown)
    for parcel_id in targets:
        with SessionLocal() as db:
            try:
                request, created = imagery_service._create_queued_request(db, parcel_id)
            except IntegrityError:
                skipped += 1
                print(f"  skipped {parcel_id} — could not create request")
                continue
            if not created:
                skipped += 1
                print(f"  skipped {parcel_id} — request already in flight")
                continue
            dispatched = imagery_service.dispatch_timeline_task(db, request)

        if not dispatched:
            skipped += 1
            print(f"  skipped {parcel_id} — broker unavailable")
            continue

        queued += 1
        print(f"  queued {request.id} for parcel {parcel_id}")

    print(f"\nDone — queued {queued} timeline request(s), skipped {skipped}.")


if __name__ == "__main__":
    main()
