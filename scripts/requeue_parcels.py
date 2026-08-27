#!/usr/bin/env python3
"""Re-queue timelines for specific parcels, or for what the ledger selects.

The general heal path, and since M3 the delivery mechanism ledger selection
runs through. Three shapes:

* **ids, full scope** — the original. An audit named these parcels; re-run
  everything for them.
* **``--sources``** — the same, narrowed. Only the named sources get task
  rows and only they are fetched; every other source's snapshots and ledger
  history are untouched.
* **``--from-ledger``** — the parcels and their per-parcel scopes come from
  the ledger rather than from the command line, through the same
  ``services/ledger.py`` query ``scripts/ledger_gaps.py`` reports on and
  ``maybe_refetch_for_backfill`` dispatches on. What is selected is what the
  retry policy says to retry, so an operator cannot heal on a different
  definition of "still broken" than the report they read first.

``--sources`` names sources the way the **ledger** does, so
``census_decennial`` is a legal value and narrows selection to that dataset;
the request it creates declares the task source that would re-run it
(``census``). Ledger selection is scope-preserving per parcel: one with only
failed Landsat years gets a Landsat-only request even in a run that also
selects a census-only parcel.

Two classes of outcome are selectable only behind an explicit flag, because
retrying them asserts that the *request* changed, not that time passed:
``absent/api_no_data`` (``--include-absent-api``, which is what the
decennial-2000 six-character tract trim needs) and
``absent/all_cloud_filtered`` (``--include-cloud-filtered``, for a change to
the 40% cloud threshold). Without the flag they are never selected, by
anything.

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
    docker compose exec api python scripts/requeue_parcels.py \
        --skip-deploy-check --sources naip <id>
    docker compose exec api python scripts/requeue_parcels.py \
        --require-sha <sha> --from-ledger --dry-run
    docker compose exec api python scripts/requeue_parcels.py \
        --require-sha <sha> --from-ledger --sources census_decennial \
        --include-absent-api
    docker compose exec api python scripts/requeue_parcels.py \
        --require-sha <sha> --from-ledger --sources census_decennial \
        --include-absent-api --groups 2000
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
from app.logging_config import configure_script_logging
from app.models.parcels import Parcel, TimelineRequest
from app.services import imagery as imagery_service
from app.services import ledger as ledger_service
from app.services.admission import AdmissionRefused
from app.services.deploy import fetch_deployed_version

logger = structlog.get_logger(__name__)

# --sources speaks the ledger's vocabulary, which is finer than the task's:
# one `census` task writes `census_decennial` and `census_acs5` rows, and
# selecting one of those two is the whole point of the decennial-2000 heal.
_CENSUS_LEDGER_SOURCES = ("census_acs5", "census_decennial")
SELECTABLE_SOURCES = tuple(sorted({*TimelineRequest.FULL_SCOPE, *_CENSUS_LEDGER_SOURCES}))

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


def ledger_filter(sources: list[str] | None) -> set[str] | None:
    """Expand ``--sources`` into the ledger source names it covers.

    ``census`` means both census datasets; every other task source names
    itself. ``None`` means no filter.
    """
    if not sources:
        return None
    expanded: set[str] = set()
    for source in sources:
        if source == "census":
            expanded.update(_CENSUS_LEDGER_SOURCES)
        else:
            expanded.add(source)
    return expanded


def select_from_ledger(
    parcel_ids: list[uuid.UUID],
    sources: list[str] | None,
    *,
    include_cloud_filtered: bool,
    include_absent_api: bool,
    groups: list[str] | None = None,
) -> dict[uuid.UUID, dict[str, list[ledger_service.LedgerGroup]]]:
    """Parcels the retry policy has work for, and the scope each one needs.

    An empty ``parcel_ids`` means the whole fleet. The scope is derived per
    parcel, not shared: a parcel with only failed Landsat years gets a
    Landsat-only request even when the run also selects a census-only parcel.

    ``groups`` is operator scope on top of the retry policy — "just 2000 this
    time" — not a substitute for it: a group current code no longer attempts
    is already excluded by ``ledger_service.is_stale`` regardless of this
    filter (Y3, ``docs/audits/2026-08-m3/STATUS.md``).
    """
    wanted = set(parcel_ids) or None
    wanted_groups = set(groups) if groups else None
    with SessionLocal() as db:
        retryable = ledger_service.retryable_groups(
            db,
            sources=ledger_filter(sources),
            include_cloud_filtered=include_cloud_filtered,
            include_absent_api=include_absent_api,
        )

    selected: dict[uuid.UUID, dict[str, list[ledger_service.LedgerGroup]]] = {}
    for group in retryable:
        if wanted is not None and group.parcel_id not in wanted:
            continue
        if wanted_groups is not None and group.group_key not in wanted_groups:
            continue
        selected.setdefault(group.parcel_id, {}).setdefault(group.task_source, []).append(group)
    return selected


def _print_ledger_selection(
    selected: dict[uuid.UUID, dict[str, list[ledger_service.LedgerGroup]]],
) -> None:
    for parcel_id in sorted(selected, key=str):
        by_source = selected[parcel_id]
        scope = ",".join(sorted(by_source))
        print(f"  would re-queue: {parcel_id} [{scope}]")
        for source in sorted(by_source):
            for group in sorted(by_source[source], key=lambda g: (g.source, g.group_key)):
                reason = f"/{group.reason}" if group.reason else ""
                print(
                    f"      {group.source} {group.group_key}"
                    f"  {group.outcome}{reason}  (attempt {group.attempts})"
                )


def _known_parcels(parcel_ids: list[uuid.UUID]) -> set[uuid.UUID]:
    with SessionLocal() as db:
        rows = db.execute(select(Parcel.id).where(Parcel.id.in_(parcel_ids))).scalars().all()
    return set(rows)


def main() -> None:
    configure_script_logging()

    parser = argparse.ArgumentParser(description="Re-queue timelines for specific parcels")
    parser.add_argument(
        "parcel_ids",
        nargs="*",
        help="Parcel UUIDs to re-queue; with --from-ledger, narrows the "
        "selection to these parcels instead of the whole fleet",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List what would be queued without queuing anything",
    )
    parser.add_argument(
        "--sources",
        nargs="+",
        metavar="SOURCE",
        choices=SELECTABLE_SOURCES,
        help="Limit the run to these sources, named as the ledger names them "
        f"({', '.join(SELECTABLE_SOURCES)}). Default: every source.",
    )
    parser.add_argument(
        "--from-ledger",
        action="store_true",
        help="Select parcels and their scopes from the per-year ledger "
        "instead of taking them from the command line",
    )
    parser.add_argument(
        "--include-cloud-filtered",
        action="store_true",
        help="Also select absent/all_cloud_filtered groups — only meaningful "
        "once the eo:cloud_cover threshold has changed",
    )
    parser.add_argument(
        "--include-absent-api",
        action="store_true",
        help="Also select absent/api_no_data groups — only meaningful once "
        "the request itself has changed (e.g. the decennial tract trim)",
    )
    parser.add_argument(
        "--groups",
        nargs="+",
        metavar="GROUP_KEY",
        help="Limit --from-ledger selection to these group keys (e.g. 2000), "
        "composable with --sources. Operator scope on top of the retry "
        "policy, not a substitute for it — a group current code no longer "
        "attempts stays excluded regardless of this flag",
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
    if not args.parcel_ids and not args.from_ledger:
        parser.error("give at least one parcel id, or --from-ledger")
    for flag, name in (
        (args.include_cloud_filtered, "--include-cloud-filtered"),
        (args.include_absent_api, "--include-absent-api"),
        (args.groups, "--groups"),
    ):
        if flag and not args.from_ledger:
            parser.error(f"{name} only means something with --from-ledger")

    _check_deploy_gate(args.api_url, args.require_sha, args.skip_deploy_check)

    try:
        parcel_ids = [uuid.UUID(raw) for raw in args.parcel_ids]
    except ValueError as exc:
        parser.error(f"not a parcel UUID: {exc}")

    known = _known_parcels(parcel_ids)
    unknown = [pid for pid in parcel_ids if pid not in known]
    for pid in unknown:
        print(f"  skipped {pid} — no such parcel")

    # scope[pid] is what that parcel's request will declare; None means full.
    scope: dict[uuid.UUID, list[str] | None]
    if args.from_ledger:
        selected = select_from_ledger(
            [pid for pid in parcel_ids if pid in known],
            args.sources,
            include_cloud_filtered=args.include_cloud_filtered,
            include_absent_api=args.include_absent_api,
            groups=args.groups,
        )
        targets = sorted(selected, key=str)
        scope = {pid: sorted(selected[pid]) for pid in targets}
        groups = sum(len(g) for by_source in selected.values() for g in by_source.values())
        print(f"Ledger selected {groups} group(s) across {len(targets)} parcel(s).")
    else:
        targets = [pid for pid in parcel_ids if pid in known]
        declared = (
            sorted({ledger_service.task_source_for(s) for s in args.sources})
            if args.sources
            else None
        )
        scope = dict.fromkeys(targets, declared)

    if not targets:
        print("Nothing to do.")
        return

    print(f"Re-queuing {len(targets)} parcel(s).")

    if args.dry_run:
        if args.from_ledger:
            _print_ledger_selection(selected)
        else:
            for pid in targets:
                sources = scope[pid]
                print(f"  would re-queue: {pid} [{','.join(sources) if sources else 'all'}]")
        return

    deadline = time.monotonic() + args.max_wait_minutes * 60
    queued = 0
    skipped = len(unknown)
    unreached: list[uuid.UUID] = []
    for index, parcel_id in enumerate(targets):
        with SessionLocal() as db:
            try:
                request, created = imagery_service.create_queued_request_waiting(
                    db, parcel_id, deadline=deadline, sources=scope[parcel_id], origin="heal"
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
        print(f"  queued {request.id} for parcel {parcel_id} [{','.join(request.sources)}]")

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
