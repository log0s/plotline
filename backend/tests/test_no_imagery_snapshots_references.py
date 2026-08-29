"""No application or script file names the retired denormalized table.

ADR 0001 step 4's delete-the-fix standard, and it is stronger than step 3's on
purpose. ``tests/test_read_cutover.py``'s docstring states step 3's: **no
serving path touches it** — the reconciler legitimately still read and wrote
it while the dual-write ran. Step 4 deleted that last contact, so the standard
inherited here is **no code at all**, and the honest way to assert "no code"
is a text search rather than a behavioural test: a behavioural test can only
fail on the paths someone thought to exercise, and the failure mode this
guards against is a path nobody thought about.

Shaped after ``tests/test_script_logging.py``'s guard — walk the real
directories, apply one rule, name the exceptions inline with their reason.

**Why the token and not the SQL.** Matching only SQL-ish contexts would let
the name survive in comments, and a comment that names a dropped table is how
the next person concludes the table is still there. So the rule is the bare
token, which costs something real and is paid deliberately: prose that used to
say "moved off ``imagery_snapshots``" now says "moved off the denormalized
table", and a reader who wants the name reads ADR 0001. **The audit trail
keeps the name** — ``docs/`` is frozen by CLAUDE.md and is not walked here,
and neither is ``alembic/versions/``, where the create and the drop both have
to spell it or they could not run.

Delete-the-fix on the deletion itself: restore ``app/models/parcels.py``'s
``ImagerySnapshot`` model, or any one of the reads step 4 removed, and
``test_no_source_file_names_the_retired_table`` goes red naming the file.
"""

from __future__ import annotations

from pathlib import Path

_HERE = Path(__file__).resolve()
# Two roots, found independently. The repository lays them out as
# ``backend/app`` and ``scripts``; the container image flattens both under
# ``/app``. Deriving each from a file it must contain works in either.
_APP = next(p / "app" for p in _HERE.parents if (p / "app" / "services" / "imagery.py").exists())
_SCRIPTS = next(p / "scripts" for p in _HERE.parents if (p / "scripts" / "seed.py").exists())

_SEARCHED = (_APP, _SCRIPTS)

# The **table name**, and only it. The ORM class was ``ImagerySnapshot``, but
# matching that too would catch ``ImagerySnapshotResponse`` in
# ``app/schemas/imagery.py`` — the API response model, which is named for the
# domain concept the endpoint still serves and has nothing to do with the
# storage. Restoring the model cannot dodge this token anyway: it would carry
# ``__tablename__ = "imagery_snapshots"``, the two constraint names, and the
# ``Parcel.imagery_snapshots`` relationship, so delete-the-fix holds on the
# narrower rule.
TOKENS = ("imagery_snapshots",)

# The one file that may name it, and why the exception is principled rather
# than convenient: `snapshot_reads.py` is the *instrument* of the cooling
# measurement. It queries `pg_stat_user_tables` and never the table itself —
# the name appears only as a value in a `relname IN (...)` filter — so it is
# not a code contact in the sense this test polices. It is also the thing that
# proves the claim: a measurement of "nothing accessed this table" has to be
# able to say which table.
ALLOWED = {_SCRIPTS / "snapshot_reads.py"}

# Directories that are not application code and are never walked.
_SKIP_DIRS = {"__pycache__", ".venv", "node_modules"}


def _source_files() -> list[Path]:
    out = []
    for root in _SEARCHED:
        for path in root.rglob("*.py"):
            if _SKIP_DIRS & set(path.parts):
                continue
            out.append(path)
    return sorted(out)


def test_the_search_actually_covers_the_code() -> None:
    """A guard that walks an empty tree passes for the wrong reason.

    The paths are derived by walking up for a file each must contain, so a
    move or a layout change would silently empty them. Assert the corpus is
    real, and contains both the service the cutover changed and the one
    allowlisted script, before asserting anything about its contents.
    """
    files = set(_source_files())
    assert len(files) > 40, f"only {len(files)} source files found — the search paths are wrong"
    assert _APP / "services" / "imagery.py" in files
    assert _SCRIPTS / "snapshot_reads.py" in files


def test_no_source_file_names_the_retired_table() -> None:
    offenders: dict[str, list[str]] = {}
    for path in _source_files():
        if path in ALLOWED:
            continue
        hits = [token for token in TOKENS if token in path.read_text()]
        if hits:
            offenders[path.name] = hits

    assert not offenders, (
        "ADR 0001 step 4 retired this table; these files still name it: "
        f"{offenders}. If a new file legitimately needs the name — which after "
        "migration 0019 means it is measuring the table's absence, not using "
        "it — add it to ALLOWED with the reason."
    )


def test_the_allowlist_names_only_files_that_exist() -> None:
    """An allowlist entry for a deleted file silently widens the rule."""
    missing = [str(path) for path in ALLOWED if not path.exists()]
    assert not missing, f"ALLOWED names files that do not exist: {missing}"
