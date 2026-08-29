#!/usr/bin/env python3
"""Re-queue timelines for parcels that have Landsat imagery.

Older Landsat scenes (1984–1990s) sometimes lose asset availability on
Planetary Computer and start returning 502s from the tile server. A re-run
re-validates each selected scene's bands and swaps in the next-best
candidate for that year, then reconciliation deletes the scene it replaced
— so a parcel ends up with one working card per year rather than a working
card next to a broken one.

Because it re-runs the whole pipeline, this is also the fleet-wide sweep
used to realise a selection-changing imagery fix — the 2026-08-25
Sentinel-2 year-grouping change was swept this way.

Parcels with a timeline request already in flight are skipped and logged;
the batch continues. Re-running the script is therefore safe.

Admission
---------
Every new request passes through ``ensure_admission``, which refuses once
``max_inflight_timeline_requests`` (30) requests are ``queued`` or
``processing``. A sweep enqueues far faster than the worker drains, so on
any fleet larger than the cap the refusal is not an exception — it is the
normal steady state, reached within seconds.

This script used to catch only ``IntegrityError``, so the first refusal
propagated and abandoned every parcel behind it: the 2026-08-25 sweep
reached 30 of 184 parcels and stopped (see
``docs/audits/2026-08-s2-year/HEAL-SCORECARD.md`` §2 and §11.1). It now
waits for a slot instead, polling the same in-flight count the admission
check gates on, and gives up only when ``--max-wait-minutes`` is exhausted
— at which point it names the parcels it never reached and exits non-zero,
so an incomplete sweep cannot be mistaken for a complete one.

The kill switch (``ACCEPT_NEW_PARCELS=false``) is never waited out. It is
off by operator intent and waiting does not change it.

Resuming an interrupted sweep
-----------------------------
``--skip-swept-since`` excludes parcels whose most recent ``complete``
timeline request was created after the deploy carrying a given SHA, so a
follow-up run finishes the fleet rather than re-running what already ran.
Nothing in the schema records which code a request ran under —
``timeline_requests`` has no SHA column — so the SHA is resolved the same
way ``requeue_parcels.py``'s gate resolves it, against the running API's
``/api/v1/health``, and the cutoff is that image's ``built`` time.

**``built`` is the image build time, not the rollout time.** A request
created in the gap between the two ran against the *previous* code and
will still be skipped. The gap is the tail of the CI job — minutes — but
it is real, and ``--since <ISO timestamp>`` exists for when it matters:
pass the moment the deploy actually went live and the cutoff is exact.

Usage (API + worker must be running):
    docker compose exec api python scripts/revalidate_landsat.py
    docker compose exec api python scripts/revalidate_landsat.py --dry-run
    docker compose exec api python scripts/revalidate_landsat.py \\
        --skip-swept-since <sha> --max-wait-minutes 90
    docker compose exec api python scripts/revalidate_landsat.py \\
        --since 2026-08-25T19:00:00Z
"""

from __future__ import annotations

import argparse
import sys
import time
import uuid
from datetime import UTC, datetime
from typing import NoReturn

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import SessionLocal
from app.logging_config import configure_script_logging
from app.models.parcels import TimelineRequest
from app.services import imagery as imagery_service
from app.services.admission import AdmissionRefused
from app.services.deploy import fetch_deployed_version


def landsat_parcels(db: Session) -> list[uuid.UUID]:
    """Parcels serving at least one Landsat period.

    Reads ``parcel_scenes`` since the ADR 0001 step-3 cutover; it used to
    ``GROUP BY parcel_id`` over ``imagery_snapshots``. The two agreed exactly
    on every parcel of the local fleet when both paths were alive
    (`docs/audits/2026-08-normalization/step3-parity-local.md`, site
    ``revalidate_landsat``).
    """
    return imagery_service.parcels_serving_source(db, "landsat")


def swept_since(db: Session, cutoff: datetime) -> set[uuid.UUID]:
    """Parcels whose most recent ``complete`` request was created at/after ``cutoff``.

    "Most recent" rather than "any": a parcel swept under the new code and
    then re-run under the old one has not been swept, and ``max`` is what
    says so.
    """
    rows = (
        db.execute(
            select(TimelineRequest.parcel_id)
            # Full scope only, and 'partial' counts: this asks "was the whole
            # pipeline re-run under the new code", which a scoped backfill is
            # not, and which a run that lost one source still was.
            .where(imagery_service.full_scope_clause(db))
            .where(TimelineRequest.status.in_(("complete", "partial")))
            .group_by(TimelineRequest.parcel_id)
            .having(func.max(TimelineRequest.created_at) >= cutoff)
        )
        .scalars()
        .all()
    )
    return set(rows)


def _refuse(problem: str) -> NoReturn:
    print(f"REFUSING to sweep — {problem}", file=sys.stderr)
    sys.exit(1)


def resolve_cutoff(api_url: str, sha_prefix: str) -> datetime:
    """Build time of the running deploy, once it is confirmed to be ``sha_prefix``.

    Refuses rather than guessing: a mismatched SHA means the operator is
    naming a deploy that is not the one running, and skipping parcels on
    that basis would silently drop them from the sweep.
    """
    try:
        version = fetch_deployed_version(api_url)
    except RuntimeError as exc:
        _refuse(f"could not read the deployed version: {exc}")

    if not version.sha.lower().startswith(sha_prefix.lower()):
        _refuse(
            f"prod is running {version.sha}, not {sha_prefix}. "
            "--skip-swept-since names the deploy whose sweep is being resumed; "
            "use --since <ISO timestamp> to skip against a deploy that is no "
            "longer running."
        )

    if version.built is None:
        _refuse(
            f"prod reports {version.sha} but no usable build time, so there is "
            "no cutoff to skip against. Use --since <ISO timestamp>."
        )

    return version.built


def _parse_since(raw: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        _refuse(f"--since {raw!r} is not an ISO 8601 timestamp")
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def main() -> None:
    configure_script_logging()

    parser = argparse.ArgumentParser(description="Re-queue Landsat timelines")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List affected parcels without queuing anything",
    )
    parser.add_argument(
        "--max-wait-minutes",
        type=float,
        default=60.0,
        help="Total time to spend waiting for admission slots before giving "
        "up and reporting the parcels not reached (default: 60)",
    )
    parser.add_argument(
        "--api-url",
        default=get_settings().api_internal_url,
        help="Base URL of the running API to read /api/v1/health from",
    )
    skip = parser.add_mutually_exclusive_group()
    skip.add_argument(
        "--skip-swept-since",
        metavar="SHA",
        help="Skip parcels whose latest complete request postdates the build "
        "time of the deploy reporting this SHA (must be the running deploy)",
    )
    skip.add_argument(
        "--since",
        metavar="ISO",
        help="Skip parcels whose latest complete request postdates this "
        "timestamp — exact, and independent of what is deployed",
    )
    args = parser.parse_args()

    if args.max_wait_minutes < 0:
        parser.error("--max-wait-minutes cannot be negative")

    with SessionLocal() as db:
        parcel_ids = landsat_parcels(db)
    if not parcel_ids:
        print("No parcels with Landsat imagery found.")
        return

    print(f"Found {len(parcel_ids)} parcel(s) with Landsat imagery.")

    if args.skip_swept_since or args.since:
        if args.skip_swept_since:
            cutoff = resolve_cutoff(args.api_url, args.skip_swept_since)
            print(f"Skipping parcels swept since {cutoff.isoformat()} (build time).")
        else:
            cutoff = _parse_since(args.since)
            print(f"Skipping parcels swept since {cutoff.isoformat()}.")
        with SessionLocal() as db:
            already = swept_since(db, cutoff)
        before = len(parcel_ids)
        parcel_ids = [pid for pid in parcel_ids if pid not in already]
        print(f"  {before - len(parcel_ids)} already swept; {len(parcel_ids)} to go.")
        if not parcel_ids:
            print("Nothing to do.")
            return

    if args.dry_run:
        for pid in parcel_ids:
            print(f"  would re-queue: {pid}")
        return

    deadline = time.monotonic() + args.max_wait_minutes * 60
    queued = 0
    skipped = 0
    unreached: list[uuid.UUID] = []

    for index, parcel_id in enumerate(parcel_ids):
        with SessionLocal() as db:
            # Goes through the service so the one-in-flight-per-parcel index
            # is a skip, not a crash that kills the rest of the batch — and
            # so a full queue is a wait rather than an abandoned sweep.
            try:
                request, created = imagery_service.create_queued_request_waiting(
                    db, parcel_id, deadline=deadline, origin="heal"
                )
            except AdmissionRefused as exc:
                unreached = list(parcel_ids[index:])
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
        print(
            "\nThe sweep is incomplete. Re-run once the queue has drained; "
            "--skip-swept-since <deployed sha> will pick up where this stopped.",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
