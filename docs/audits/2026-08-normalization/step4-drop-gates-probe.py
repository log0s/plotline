"""ADR 0001 step 4 deploy-2 verification probe. Read-only, transaction-scoped."""
import json
from sqlalchemy import text as sa_text
from sqlalchemy.exc import InternalError, ProgrammingError
from app.db import SessionLocal
from app.logging_config import configure_script_logging
from scripts.shared.probe import audit_probe, probe_count

configure_script_logging()
out = {}
with SessionLocal() as db:
    db.execute(sa_text("SET TRANSACTION READ ONLY"))

    # read-only proof, inside this same transaction, on a savepoint
    try:
        with db.begin_nested():
            db.execute(sa_text("UPDATE scenes SET fetched_at = fetched_at WHERE false"))
        out["read_only_proof"] = "FAILED — the UPDATE was accepted"
    except (InternalError, ProgrammingError) as exc:
        out["read_only_proof"] = type(exc.orig).__name__ + ": " + str(exc.orig).strip()

    out["alembic_version"] = db.execute(
        sa_text("SELECT version_num FROM alembic_version")
    ).scalar()

    out["to_regclass_imagery_snapshots"] = db.execute(
        sa_text("SELECT to_regclass('public.imagery_snapshots')::text")
    ).scalar()

    out["pg_class_relname_like"] = [
        dict(r) for r in db.execute(sa_text(
            "SELECT c.relname, c.relkind, n.nspname FROM pg_class c"
            " JOIN pg_namespace n ON n.oid = c.relnamespace"
            " WHERE c.relname LIKE '%imagery_snapshot%'"
        )).mappings()
    ]

    out["pg_index_on_table"] = [
        dict(r) for r in db.execute(sa_text(
            "SELECT indexrelid::regclass::text AS idx, indrelid::regclass::text AS tbl"
            " FROM pg_index WHERE indrelid = to_regclass('public.imagery_snapshots')"
        )).mappings()
    ]

    out["pg_constraint_named"] = [
        dict(r) for r in db.execute(sa_text(
            "SELECT conname, contype, conrelid::regclass::text AS tbl"
            " FROM pg_constraint WHERE conname LIKE '%imagery_snapshot%'"
            " OR conrelid = to_regclass('public.imagery_snapshots')"
        )).mappings()
    ]

    out["pg_stat_user_tables_imagery"] = [
        dict(r) for r in db.execute(sa_text(
            "SELECT relname FROM pg_stat_user_tables WHERE relname LIKE '%imagery%'"
        )).mappings()
    ]

    out["all_public_tables"] = [
        r[0] for r in db.execute(sa_text(
            "SELECT relname FROM pg_stat_user_tables ORDER BY relname"
        ))
    ]

    out["ck_scenes_footprint_valid"] = [
        dict(r) for r in db.execute(sa_text(
            "SELECT conname, contype, convalidated,"
            " pg_get_constraintdef(oid) AS def"
            " FROM pg_constraint WHERE conrelid = 'public.scenes'::regclass"
            " ORDER BY conname"
        )).mappings()
    ]

    out["counts"] = {
        "parcels": probe_count(db, "parcels", purpose="step-4 deploy-2 close-out totals"),
        "scenes": probe_count(db, "scenes", purpose="step-4 deploy-2 close-out totals"),
        "parcel_scenes": probe_count(db, "parcel_scenes", purpose="step-4 deploy-2 close-out totals"),
    }

    audit_probe("pg_stat_database", purpose="step-4 deploy-2 stats_reset check")
    out["stats_reset"] = str(db.execute(sa_text(
        "SELECT stats_reset FROM pg_stat_database WHERE datname = current_database()"
    )).scalar())

    out["now"] = str(db.execute(sa_text("SELECT now()")).scalar())
    db.rollback()

print(json.dumps(out, indent=2, default=str))
