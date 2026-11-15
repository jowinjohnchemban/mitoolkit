"""Work out the next release version from what was merged since the last release.

Used by the Release workflow on every merge to main. The git tag is the source of truth for the version: the
last tag vMAJOR.MINOR.PATCH plus a bump decided by the pull request titles merged since (Conventional Commits):

    breaking:  "type!: ..." or "BREAKING CHANGE" in the message           -> major
    feature:   "feat: ..."                                                -> minor
    anything else ("fix: ...", "docs: ...", "ci: ...", ...)               -> patch

The biggest bump among the merges since the last release wins. A pull request label major, minor or patch
overrides its title. "[skip release]" in a title means no release for that merge (the next one carries it).

Prints GITHUB_OUTPUT lines: release=true|false, tag=vX.Y.Z, version=X.Y.Z, bump=major|minor|patch.
Run with ``--bump major|minor|patch`` (the workflow's manual input) to force a bump.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from typing import Iterable, List, Optional, Tuple

ORDER = {"patch": 1, "minor": 2, "major": 3}
TITLE = re.compile(r"^(?P<type>[a-z]+)(\([^)]*\))?(?P<bang>!)?: ", re.I)
SEMVER = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")


def parse_tag(tag: str) -> Optional[Tuple[int, int, int]]:
    m = SEMVER.match(tag.strip())
    return (int(m[1]), int(m[2]), int(m[3])) if m else None


def bump_for(message: str, labels: Iterable[str] = ()) -> Optional[str]:
    """The bump one merged change asks for, or None for "[skip release]"."""
    if "[skip release]" in message.lower():
        return None
    for label in labels:
        if label.lower() in ORDER:
            return label.lower()
    subject = message.splitlines()[0] if message else ""
    m = TITLE.match(subject)
    if (m and m["bang"]) or "BREAKING CHANGE" in message:
        return "major"
    if m and m["type"].lower() in ("feat", "feature"):
        return "minor"
    return "patch"


def biggest(bumps: Iterable[Optional[str]]) -> Optional[str]:
    found = [b for b in bumps if b]
    return max(found, key=ORDER.__getitem__) if found else None


def next_version(last: Tuple[int, int, int], bump: str) -> Tuple[int, int, int]:
    major, minor, patch = last
    if bump == "major":
        return major + 1, 0, 0
    if bump == "minor":
        return major, minor + 1, 0
    return major, minor, patch + 1


def decide(last_tag: Optional[str], messages: List[Tuple[str, List[str]]], forced: str = "") -> Tuple[Optional[str], str]:
    """(tag, bump) for the next release, or (None, reason) when there is nothing to release."""
    if forced:
        bump = forced
    else:
        bump = biggest(bump_for(message, labels) for message, labels in messages)
        if not messages:
            return None, "nothing was merged since the last release"
        if bump is None:
            return None, "every merge since the last release says [skip release]"
    last = parse_tag(last_tag) if last_tag else None
    version = next_version(last, bump) if last else (1, 0, 0)
    return "v{}.{}.{}".format(*version), bump


# ---------------------------------------------------------------------------------------------------- git
def git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout.strip()


def latest_tag() -> Optional[str]:
    tags = [t for t in git("tag", "--list", "v[0-9]*").splitlines() if parse_tag(t)]
    return max(tags, key=parse_tag) if tags else None


def labels_of(sha: str) -> List[str]:
    """Labels of the pull request a commit was merged from (empty without a token or a pull request)."""
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not repo or not os.environ.get("GH_TOKEN"):
        return []
    try:
        out = subprocess.run(["gh", "api", f"repos/{repo}/commits/{sha}/pulls", "--jq",
                              ".[0].labels[].name"], capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return []
    return out.split()


def merged_since(tag: Optional[str]) -> List[Tuple[str, List[str]]]:
    span = f"{tag}..HEAD" if tag else "HEAD"
    shas = git("log", span, "--format=%H").splitlines()
    return [(git("log", "-1", "--format=%B", sha), labels_of(sha)) for sha in shas]


def main(argv: List[str]) -> int:
    forced = ""
    if "--bump" in argv:
        forced = argv[argv.index("--bump") + 1].strip().lower()
        if forced and forced not in ORDER:
            print(f"--bump must be major, minor or patch, not {forced!r}", file=sys.stderr)
            return 2
    tag = latest_tag()
    if tag and git("tag", "--points-at", "HEAD").split() and tag in git("tag", "--points-at", "HEAD").split():
        print("release=false")
        print(f"{tag} already points at this commit: nothing to release", file=sys.stderr)
        return 0
    new_tag, bump = decide(tag, merged_since(tag), forced)
    if new_tag is None:
        print("release=false")
        print(bump, file=sys.stderr)
        return 0
    print("release=true")
    print(f"tag={new_tag}")
    print(f"version={new_tag[1:]}")
    print(f"bump={bump}")
    print(f"{tag or 'no release yet'} -> {new_tag} ({bump})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
