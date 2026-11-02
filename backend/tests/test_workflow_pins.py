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


_DEPLOY = _WORKFLOWS / "deploy.yml"
_CHECKSUM = re.compile(r'echo "\$\{FLYCTL_SHA256\}  (\S+)" \| sha256sum -c -')


def _steps_by_job(text: str) -> dict[str, list[str]]:
    jobs: dict[str, list[str]] = {}
    job = ""
    for line in text.split("\n"):
        if m := re.match(r"^  ([\w-]+):\s*$", line):
            job = m.group(1)
            jobs[job] = []
        elif job and re.match(r"^      - ", line):
            jobs[job].append(line + "\n")
        elif job and jobs[job]:
            jobs[job][-1] += line + "\n"
    return jobs


@pytest.mark.skipif(not _DEPLOY.exists(), reason=f"{_DEPLOY} not present")
def test_flyctl_is_pinned_and_checksum_verified_before_it_runs() -> None:
    """SEC-19: flyctl holds FLY_API_TOKEN, so its bytes are verified first."""
    text = _DEPLOY.read_text()
    assert re.search(r'^  FLYCTL_VERSION: "\d+\.\d+\.\d+"$', text, re.M)
    assert re.search(r'^  FLYCTL_SHA256: "[0-9a-f]{64}"$', text, re.M)
    assert not re.search(r"^\s*-?\s*uses:\s*superfly/flyctl-actions", text, re.M)

    deploy_jobs = {
        name: steps
        for name, steps in _steps_by_job(text).items()
        if any("flyctl deploy" in s for s in steps)
    }
    assert set(deploy_jobs) == {"deploy-api", "deploy-worker", "deploy-titiler"}
    for name, steps in deploy_jobs.items():
        installs = [i for i, s in enumerate(steps) if "flyctl.tgz" in s]
        deploy = next(i for i, s in enumerate(steps) if "flyctl deploy" in s)
        assert len(installs) == 1, name
        install = steps[installs[0]]
        assert installs[0] < deploy, name
        m = _CHECKSUM.search(install)
        assert m, f"{name}: no sha256sum -c of the download"
        assert install.index(m.group(0)) < install.index("tar -x"), name
        assert f'-o "{m.group(1)}"' in install, f"{name}: checks a different file"
