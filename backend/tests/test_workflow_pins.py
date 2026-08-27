"""Every third-party GitHub Action is pinned to a commit SHA (security audit SEC-9)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"
_USES = re.compile(r"^\s*-?\s*uses:\s*(\S+)")
_PINNED = re.compile(r"^[\w.-]+/[\w.-]+(?:/[\w.-]+)*@[0-9a-f]{40}$")


@pytest.mark.skipif(
    not _WORKFLOWS.exists(),
    reason=(
        f"{_WORKFLOWS} not present; the compose test container only mounts "
        "./backend and ./scripts, not the repo's .github/ directory"
    ),
)
def test_every_action_is_pinned_to_a_commit_sha() -> None:
    files = sorted(_WORKFLOWS.glob("*.yml"))
    assert files, "no workflows found"
    unpinned = []
    for path in files:
        for line in path.read_text().splitlines():
            m = _USES.match(line)
            if m and not _PINNED.match(m.group(1)):
                unpinned.append(f"{path.name}: {m.group(1)}")
    assert unpinned == []
