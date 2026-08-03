#!/usr/bin/env python3
"""Publish the Sheet-driven site to versioned releases on the KAIST server.

The publisher runs without Docker or sudo access.  It keeps a dedicated,
read-only-purpose Git checkout, builds into a staging directory, validates the
complete site, and only then atomically switches the ``current`` symlink used
by Nginx.  A failed fetch, build, or validation never replaces the last good
release.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterator, List, Sequence


DEFAULT_REMOTE_URL = "https://github.com/econaikaist/econai_web.git"
DEFAULT_BRANCH = "main"
DEFAULT_SHEET_ID = "14pRbiM3ubsGT1DsBZdLF9xSHmSntwBRSkAUYbyrr6xM"
DEFAULT_CHECKOUT_DIR = Path("/var/lib/econai-publisher/repository")
DEFAULT_DEPLOY_ROOT = Path("/srv/econai-site")
MANAGED_CHECKOUT_MARKER = ".econai-publisher-managed"
BUILD_METADATA_PATH = Path("data/sheet-build.json")


class PublishError(RuntimeError):
    """Raised when a release cannot be published safely."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run(
    command: Sequence[str],
    cwd: Path | None = None,
    *,
    echo_output: bool = True,
) -> str:
    environment = os.environ.copy()
    environment.update(
        {
            "GIT_TERMINAL_PROMPT": "0",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    result = subprocess.run(
        list(command),
        cwd=cwd,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if echo_output and result.stdout.strip():
        print(result.stdout.rstrip())
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or "no diagnostic output"
        raise PublishError(f"command failed ({result.returncode}): {' '.join(command)}\n{detail}")
    return result.stdout.strip()


def _validate_managed_path(path: Path, label: str) -> Path:
    if path.is_symlink():
        raise PublishError(f"{label} must not be a symlink: {path}")
    resolved = path.resolve()
    if resolved in {Path("/"), Path("/srv"), Path("/var"), Path("/var/lib")}:
        raise PublishError(f"refusing broad {label}: {resolved}")
    if len(resolved.parts) < 3:
        raise PublishError(f"refusing shallow {label}: {resolved}")
    return resolved


def _git_output(checkout_dir: Path, *arguments: str) -> str:
    return _run(
        ["git", "-C", str(checkout_dir), *arguments],
        echo_output=False,
    )


def _initial_clone(checkout_dir: Path, remote_url: str, branch: str) -> None:
    parent = checkout_dir.parent
    parent.mkdir(parents=True, exist_ok=True)
    temporary = parent / f".repository-{uuid.uuid4().hex}"
    try:
        _run(
            [
                "git",
                "clone",
                "--quiet",
                "--single-branch",
                "--branch",
                branch,
                "--no-tags",
                remote_url,
                str(temporary),
            ]
        )
        (temporary / MANAGED_CHECKOUT_MARKER).write_text(
            json.dumps({"remote": remote_url, "branch": branch}) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, checkout_dir)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def prepare_checkout(checkout_dir: Path, remote_url: str, branch: str) -> tuple[Path, str]:
    checkout_dir = _validate_managed_path(checkout_dir, "checkout directory")
    if not checkout_dir.exists():
        _initial_clone(checkout_dir, remote_url, branch)

    marker_path = checkout_dir / MANAGED_CHECKOUT_MARKER
    if not (checkout_dir / ".git").is_dir() or not marker_path.is_file():
        raise PublishError(
            f"refusing unmanaged checkout at {checkout_dir}; expected {MANAGED_CHECKOUT_MARKER}"
        )
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PublishError(f"invalid managed-checkout marker: {exc}") from exc
    if marker != {"remote": remote_url, "branch": branch}:
        raise PublishError("managed checkout remote or branch differs from configured source")

    configured_remote = _git_output(checkout_dir, "remote", "get-url", "origin")
    if configured_remote != remote_url:
        raise PublishError(
            f"checkout origin mismatch: expected {remote_url!r}, found {configured_remote!r}"
        )
    dirty = _git_output(checkout_dir, "status", "--porcelain", "--untracked-files=no")
    if dirty:
        raise PublishError(f"managed checkout has tracked modifications:\n{dirty}")

    try:
        _git_output(checkout_dir, "fetch", "--quiet", "--no-tags", "origin", branch)
        fetched_sha = _git_output(checkout_dir, "rev-parse", "FETCH_HEAD")
        _git_output(checkout_dir, "checkout", "--quiet", "--detach", "--force", fetched_sha)
        source_sha = fetched_sha
    except PublishError as exc:
        source_sha = _git_output(checkout_dir, "rev-parse", "HEAD")
        print(
            f"WARNING: GitHub refresh failed; using existing source {source_sha[:12]}: {exc}",
            file=sys.stderr,
        )

    for required in ("main_site", "scripts/build_sheet_site.py", "scripts/validate_site.py"):
        if not (checkout_dir / required).exists():
            raise PublishError(f"source checkout is missing {required}")
    return checkout_dir, source_sha


def source_from_local_repository(source_repo: Path) -> tuple[Path, str]:
    source_repo = source_repo.resolve()
    for required in ("main_site", "scripts/build_sheet_site.py", "scripts/validate_site.py"):
        if not (source_repo / required).exists():
            raise PublishError(f"local source repository is missing {required}")
    try:
        source_sha = _git_output(source_repo, "rev-parse", "HEAD")
    except PublishError:
        source_sha = "local"
    return source_repo, source_sha


def _normalised_file_payload(path: Path, relative_path: Path) -> bytes:
    payload = path.read_bytes()
    if relative_path != BUILD_METADATA_PATH:
        return payload
    try:
        metadata = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PublishError(f"invalid generated build metadata: {exc}") from exc
    metadata.pop("built_at", None)
    return json.dumps(
        metadata,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def site_digest(site_dir: Path) -> str:
    digest = hashlib.sha256()
    files: List[Path] = []
    for candidate in site_dir.rglob("*"):
        if candidate.is_symlink():
            raise PublishError(
                f"generated site contains a forbidden symlink: {candidate.relative_to(site_dir)}"
            )
        if candidate.is_file():
            files.append(candidate)
    for path in sorted(files, key=lambda value: value.relative_to(site_dir).as_posix()):
        relative = path.relative_to(site_dir)
        payload = _normalised_file_payload(path, relative)
        digest.update(relative.as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(len(payload)).encode("ascii"))
        digest.update(b"\0")
        digest.update(payload)
        digest.update(b"\0")
    return digest.hexdigest()


def _current_release(deploy_root: Path) -> Path | None:
    current = deploy_root / "current"
    if not os.path.lexists(current):
        return None
    if not current.is_symlink():
        raise PublishError(f"refusing non-symlink current path: {current}")
    target = (current.parent / os.readlink(current)).resolve()
    releases = (deploy_root / "releases").resolve()
    if not target.is_relative_to(releases) or not target.is_dir():
        raise PublishError(f"current points outside valid releases: {target}")
    return target


def activate_release(release: Path, deploy_root: Path) -> None:
    release = release.resolve()
    releases = (deploy_root / "releases").resolve()
    if not release.is_relative_to(releases) or not release.is_dir():
        raise PublishError(f"refusing invalid release activation: {release}")
    current = deploy_root / "current"
    if os.path.lexists(current) and not current.is_symlink():
        raise PublishError(f"refusing to replace non-symlink current path: {current}")
    temporary_link = deploy_root / f".current-{uuid.uuid4().hex}"
    relative_target = release.relative_to(deploy_root.resolve())
    try:
        temporary_link.symlink_to(relative_target, target_is_directory=True)
        os.replace(temporary_link, current)
    finally:
        if os.path.lexists(temporary_link):
            temporary_link.unlink()


def _write_status(deploy_root: Path, status: Dict[str, object]) -> None:
    state_dir = deploy_root / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    target = state_dir / "status.json"
    temporary = state_dir / f".status-{uuid.uuid4().hex}.json"
    try:
        temporary.write_text(
            json.dumps(status, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()


def _prune_releases(deploy_root: Path, keep_releases: int) -> None:
    releases_dir = deploy_root / "releases"
    current = _current_release(deploy_root)
    releases = [
        path
        for path in releases_dir.iterdir()
        if path.is_dir() and not path.name.startswith(".staging-")
    ]
    releases.sort(key=lambda path: path.stat().st_mtime_ns, reverse=True)
    kept = 0
    for release in releases:
        if current is not None and release.resolve() == current.resolve():
            kept += 1
            continue
        if kept < keep_releases:
            kept += 1
            continue
        if not release.resolve().is_relative_to(releases_dir.resolve()):
            raise PublishError(f"refusing release cleanup outside {releases_dir}: {release}")
        shutil.rmtree(release)


@contextmanager
def publisher_lock(deploy_root: Path) -> Iterator[None]:
    state_dir = deploy_root / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    lock_path = state_dir / "publisher.lock"
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise PublishError("another publisher run is already active") from exc
        yield


def publish_once(args: argparse.Namespace) -> str:
    deploy_root = _validate_managed_path(args.deploy_root, "deploy root")
    releases_dir = deploy_root / "releases"
    releases_dir.mkdir(parents=True, exist_ok=True)

    with publisher_lock(deploy_root):
        if args.source_repo:
            source_repo, source_sha = source_from_local_repository(args.source_repo)
        else:
            source_repo, source_sha = prepare_checkout(
                args.checkout_dir,
                args.remote_url,
                args.branch,
            )

        staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=releases_dir))
        try:
            build_command = [
                sys.executable,
                str(source_repo / "scripts/build_sheet_site.py"),
                "--sheet-id",
                args.sheet_id,
                "--source-dir",
                str(source_repo / "main_site"),
                "--output-dir",
                str(staging),
                "--timeout",
                str(args.timeout),
            ]
            if args.csv_dir:
                build_command.extend(["--csv-dir", str(args.csv_dir.resolve())])
            _run(build_command, cwd=source_repo)
            _run(
                [
                    sys.executable,
                    str(source_repo / "scripts/validate_site.py"),
                    str(staging),
                ],
                cwd=source_repo,
            )

            content_digest = site_digest(staging)
            current = _current_release(deploy_root)
            if current is not None and site_digest(current) == content_digest:
                shutil.rmtree(staging)
                _write_status(
                    deploy_root,
                    {
                        "checked_at": _utc_now(),
                        "content_sha256": content_digest,
                        "git_sha": source_sha,
                        "release": current.name,
                        "result": "no_change",
                    },
                )
                print(f"PUBLISH_RESULT=no_change release={current.name}")
                return "no_change"

            release = releases_dir / content_digest[:20]
            if release.exists():
                if site_digest(release) != content_digest:
                    raise PublishError(f"release digest collision at {release}")
                shutil.rmtree(staging)
            else:
                os.replace(staging, release)
            os.utime(release, None)
            activate_release(release, deploy_root)
            _write_status(
                deploy_root,
                {
                    "checked_at": _utc_now(),
                    "content_sha256": content_digest,
                    "deployed_at": _utc_now(),
                    "git_sha": source_sha,
                    "release": release.name,
                    "result": "deployed",
                },
            )
            _prune_releases(deploy_root, args.keep_releases)
            print(f"PUBLISH_RESULT=deployed release={release.name}")
            return "deployed"
        finally:
            if staging.exists():
                shutil.rmtree(staging)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--remote-url", default=DEFAULT_REMOTE_URL)
    parser.add_argument("--branch", default=DEFAULT_BRANCH)
    parser.add_argument("--sheet-id", default=DEFAULT_SHEET_ID)
    parser.add_argument("--checkout-dir", type=Path, default=DEFAULT_CHECKOUT_DIR)
    parser.add_argument("--deploy-root", type=Path, default=DEFAULT_DEPLOY_ROOT)
    parser.add_argument(
        "--source-repo",
        type=Path,
        help="use an existing repository without fetching GitHub (for local verification)",
    )
    parser.add_argument(
        "--csv-dir",
        type=Path,
        help="use local CSV fixtures for all five Sheet tabs",
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--keep-releases", type=int, default=5)
    args = parser.parse_args()
    if args.keep_releases < 2:
        parser.error("--keep-releases must be at least 2")
    return args


def main() -> int:
    args = parse_args()
    try:
        publish_once(args)
    except PublishError as exc:
        print(f"site publish failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
