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

Admission
---------
A full in-flight queue (``max_inflight_timeline_requests``, 30) is a wait,
not a failure: the script polls the same count ``ensure_admission`` gates
on until a slot opens, and gives up only when ``--max-wait-minutes``
(default 60) is spent — then it names the parcels it never reached and
exits non-zero. Catching only ``IntegrityError`` here is what made the
2026-08-25 S2-year sweep abandon 154 of 184 parcels
(``docs/audits/2026-08-s2-year/ADMISSION-FIX.md``). The kill switch is
never waited out.

Deployment gate
---------------
Re-queuing re-runs scene selection against whatever code the worker is
currently running, so a heal is only as good as the deploy behind it. The
selection rules this gate exists for landed in 2039e64 (the point filter
tests each STAC item's real footprint rather than its bbox envelope, which
used to admit granules whose footprint excludes the address), e7d4c6d
(Sentinel-2 gained the validation fallback walk Landsat already had) and
14b59af (a NAIP year with no covering tile is suppressed rather than
mosaicked from its neighbours). All three are selection-time behaviour, so a
re-queue against a deploy predating them re-selects by the old rules and
heals the parcel straight back into the defect.

To make the ordering mechanical rather than a thing the operator has to
remember, the script requires the operator to pass *exactly one* of two flags, and
refuses to queue anything otherwise:

* ``--require-sha <prefix>``. The script fetches ``/api/v1/health`` from the
  running API before touching the database, reads ``version.sha`` — the SHA
  baked into the deployed image — and requires it to match. The operator
  passes the SHA of the deploy that carries the geometry fix. This is a
  prefix match against what prod reports; it does *not* walk commit history,
  so passing a SHA that merely contains the fix in its ancestry is the
  operator's judgement, not something the script verifies.
* ``--skip-deploy-check``, which logs a warning naming what was skipped and
  proceeds anyway. This is the sanctioned path for uses that do not depend
  on scene geometry.

Neither flag is a refusal, and so is both: a bare invocation is not allowed
to fall through on a warning, because the likely operator is running from
shell history days later and a warning in scrollback is not a gate.

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
    docker compose exec api python scripts/requeue_parcels.py \
        --skip-deploy-check <id> [<id> ...]
"""

from __future__ import annotations

import argparse
import sys
import time
import uuid
from typing import NoReturn

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.db import SessionLocal
from app.models.parcels import Parcel
from app.services import imagery as imagery_service
from app.services.admission import AdmissionRefused
from app.services.deploy import fetch_deployed_version

logger = structlog.get_logger(__name__)

_WHY = (
    "re-queueing through the un-fixed imagery point filter re-selects the same "
    "wrong granules, healing the parcel back into the defect"
)


def _fetch_deployed_sha(api_url: str) -> str:
    """Return ``version.sha`` from the running API's health endpoint.

    Raises ``RuntimeError`` with an operator-readable message on anything
    that leaves the SHA unknown. The fetch itself lives in
    ``app.services.deploy`` so this gate and ``revalidate_landsat.py``'s
    ``--skip-swept-since`` read the same endpoint the same way.
    """
    return fetch_deployed_version(api_url).sha


def _refuse(deployed: str, required: str) -> NoReturn:
    print("REFUSING to re-queue — deployment gate failed.", file=sys.stderr)
    print(f"  prod is running: {deployed}", file=sys.stderr)
    print(f"  required:        {required}", file=sys.stderr)
    print(f"  why: {_WHY}.", file=sys.stderr)
    print(
        "  Pass --require-sha <prefix> matching a deploy that carries the "
        "geometry fix, or --skip-deploy-check to override.",
        file=sys.stderr,
    )
    sys.exit(1)


def _refuse_flags(problem: str) -> NoReturn:
    print(f"REFUSING to re-queue — {problem}", file=sys.stderr)
    print(
        "  --require-sha <prefix>   the deployed API must report this SHA",
        file=sys.stderr,
    )
    print(
        "  --skip-deploy-check      re-queue without checking (logs a warning)",
        file=sys.stderr,
    )
    print(f"  why: {_WHY}.", file=sys.stderr)
    sys.exit(1)


def _check_deploy_gate(api_url: str, require_sha: str | None, skip: bool) -> None:
    """Exit nonzero unless the deployed SHA is vouched for, or the gate is skipped.

    Exactly one of ``require_sha`` / ``skip`` must be given; neither and both
    are refusals, checked before any network or database access.
    """
    if require_sha and skip:
        _refuse_flags("--require-sha and --skip-deploy-check are mutually exclusive.")

    if skip:
        logger.warning(
            "deploy_check_skipped",
            skipped="verification that the deployed API carries the imagery "
            "geometry fix (point-in-footprint instead of point-in-bbox)",
            danger=_WHY,
        )
        return

    if not require_sha:
        _refuse_flags("no deployment gate given. Pass exactly one of:")

    try:
        deployed = _fetch_deployed_sha(api_url)
    except RuntimeError as exc:
        _refuse(f"unknown — {exc}", require_sha)

    if deployed.lower().startswith(require_sha.lower()):
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
        help="Git SHA prefix the deployed API must report before re-queuing "
        "(required unless --skip-deploy-check)",
    )
    parser.add_argument(
        "--skip-deploy-check",
        action="store_true",
        help="Re-queue without verifying the deployed SHA (logs a warning); "
        "mutually exclusive with --require-sha",
    )
    parser.add_argument(
        "--max-wait-minutes",
        type=float,
        default=60.0,
        help="Total time to spend waiting for admission slots before giving "
        "up and reporting the parcels not reached (default: 60)",
    )
    args = parser.parse_args()

    if args.max_wait_minutes < 0:
        parser.error("--max-wait-minutes cannot be negative")

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

    deadline = time.monotonic() + args.max_wait_minutes * 60
    queued = 0
    skipped = len(unknown)
    unreached: list[uuid.UUID] = []
    for index, parcel_id in enumerate(targets):
        with SessionLocal() as db:
            try:
                request, created = imagery_service.create_queued_request_waiting(
                    db, parcel_id, deadline=deadline
                )
            except AdmissionRefused as exc:
                # Even a hand-written list of ids is worth waiting out: the
                # operator picked these parcels, and dropping the tail on a
                # transient full queue is how a heal silently half-runs.
                unreached = list(targets[index:])
                print(f"  stopping at {parcel_id} — admission refused ({exc.reason})")
                break
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

    if unreached:
        print(
            f"\n{len(unreached)} parcel(s) NOT reached — the wait budget "
            f"({args.max_wait_minutes} min) ran out:",
            file=sys.stderr,
        )
        for pid in unreached:
            print(f"  unreached: {pid}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
