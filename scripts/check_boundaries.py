#!/usr/bin/env python3
"""Fail closed when generated toolchain files or stale SDK headers are published."""

from __future__ import annotations

import argparse
import subprocess
import sys
import tarfile
from pathlib import Path, PurePosixPath


class BoundaryError(RuntimeError):
    """A repository ownership or published-header invariant was violated."""


def canonical_headers(userspace_root: Path) -> dict[str, Path]:
    headers: dict[str, Path] = {}
    roots = (
        userspace_root / "include",
        userspace_root / "runtime" / "include",
    )
    for source_root in roots:
        if not source_root.is_dir():
            raise BoundaryError(f"missing canonical userspace header root: {source_root}")
        for source in source_root.rglob("*"):
            if not source.is_file():
                continue
            relative = source.relative_to(source_root).as_posix()
            previous = headers.get(relative)
            if previous is not None and previous.read_bytes() != source.read_bytes():
                raise BoundaryError(
                    f"conflicting canonical headers for {relative}: {previous} and {source}"
                )
            headers[relative] = source
    return headers


def _files_under(root: Path) -> dict[str, Path]:
    if not root.is_dir():
        raise BoundaryError(f"missing published header directory: {root}")
    return {
        path.relative_to(root).as_posix(): path
        for path in root.rglob("*")
        if path.is_file()
    }


def _format_paths(paths: set[str]) -> str:
    return ", ".join(sorted(paths)) or "<none>"


def verify_header_tree(published_root: Path, expected: dict[str, Path], label: str) -> None:
    published = _files_under(published_root)
    expected_names = set(expected)
    published_names = set(published)
    missing = expected_names - published_names
    unexpected = published_names - expected_names
    if missing or unexpected:
        raise BoundaryError(
            f"{label} header set differs from userspace; "
            f"missing={_format_paths(missing)} unexpected={_format_paths(unexpected)}"
        )
    for relative, source in expected.items():
        if source.read_bytes() != published[relative].read_bytes():
            raise BoundaryError(
                f"{label} header differs from canonical userspace source: {relative}"
            )


def verify_sdk_archive(archive_path: Path, expected: dict[str, Path]) -> None:
    published: dict[str, bytes] = {}
    try:
        with tarfile.open(archive_path, mode="r:*") as archive:
            for member in archive.getmembers():
                prefix = "sysroot/include/"
                if not member.name.startswith(prefix) or member.name == prefix:
                    continue
                if not member.isfile():
                    raise BoundaryError(
                        f"SDK archive contains a non-file header member: "
                        f"{archive_path.name}:{member.name}"
                    )
                relative = PurePosixPath(member.name[len(prefix) :])
                if relative.is_absolute() or ".." in relative.parts:
                    raise BoundaryError(
                        f"SDK archive contains an unsafe header path: "
                        f"{archive_path.name}:{member.name}"
                    )
                name = relative.as_posix()
                if name in published:
                    raise BoundaryError(
                        f"SDK archive contains duplicate header: {archive_path.name}:{name}"
                    )
                extracted = archive.extractfile(member)
                if extracted is None:
                    raise BoundaryError(
                        f"SDK archive header cannot be read: {archive_path.name}:{member.name}"
                    )
                published[name] = extracted.read()
    except tarfile.TarError as error:
        raise BoundaryError(f"cannot read SDK archive {archive_path}: {error}") from error

    expected_names = set(expected)
    published_names = set(published)
    missing = expected_names - published_names
    unexpected = published_names - expected_names
    if missing or unexpected:
        raise BoundaryError(
            f"{archive_path.name} header set differs from userspace; "
            f"missing={_format_paths(missing)} unexpected={_format_paths(unexpected)}"
        )
    for relative, source in expected.items():
        if source.read_bytes() != published[relative]:
            raise BoundaryError(
                f"{archive_path.name} header differs from canonical userspace source: {relative}"
            )


def verify_sdk_archives(
    sdk_root: Path, expected: dict[str, Path], *, require_archives: bool = False
) -> int:
    archives = sorted(sdk_root.glob("*.tar")) if sdk_root.is_dir() else []
    if not archives:
        if require_archives:
            raise BoundaryError(f"no published SDK archives found under {sdk_root}")
        return 0
    for archive in archives:
        verify_sdk_archive(archive, expected)
    return len(archives)


def verify_tracked_paths(toolchain_root: Path) -> None:
    try:
        result = subprocess.run(
            ["git", "-C", str(toolchain_root), "ls-files", "-z"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        detail = getattr(error, "stderr", b"").decode(errors="replace").strip()
        raise BoundaryError(f"cannot inspect tracked files in {toolchain_root}: {detail}") from error

    tracked = [path for path in result.stdout.decode().split("\0") if path]
    generated = [
        path
        for path in tracked
        if PurePosixPath(path).parts[:1] in (("build",), ("sysroot",))
    ]
    if generated:
        raise BoundaryError(
            "generated toolchain files are tracked; remove these paths: "
            + _format_paths(set(generated))
        )


def parse_args() -> argparse.Namespace:
    script_root = Path(__file__).resolve().parents[1]
    repo_root = script_root.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--toolchain-root", type=Path, default=script_root)
    parser.add_argument("--userspace-root", type=Path, default=repo_root / "userspace")
    parser.add_argument("--rootfs-root", type=Path, default=repo_root / "test-rootfs")
    parser.add_argument("--sdk-root", type=Path, default=None)
    parser.add_argument(
        "--require-sdk",
        action="store_true",
        help="fail when no published SDK archive exists",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    toolchain_root = args.toolchain_root.resolve()
    userspace_root = args.userspace_root.resolve()
    rootfs_root = args.rootfs_root.resolve()
    sdk_root = (args.sdk_root or rootfs_root / "packages" / "sdk").resolve()

    verify_tracked_paths(toolchain_root)
    expected = canonical_headers(userspace_root)

    build_headers = toolchain_root / "build" / "sysroot" / "include"
    if build_headers.is_dir():
        verify_header_tree(build_headers, expected, "toolchain/build/sysroot/include")
    elif args.require_sdk:
        raise BoundaryError(f"missing generated sysroot headers: {build_headers}")

    staged_root = rootfs_root / "usr" / "include"
    if staged_root.is_dir():
        verify_header_tree(staged_root, expected, "rootfs/usr/include")

    archive_count = verify_sdk_archives(
        sdk_root, expected, require_archives=args.require_sdk
    )
    print(
        f"source-boundary check passed: {len(expected)} canonical headers, "
        f"{archive_count} SDK archives"
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BoundaryError as error:
        print(f"source-boundary check failed: {error}", file=sys.stderr)
        sys.exit(1)
