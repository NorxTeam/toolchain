from __future__ import annotations

import io
import importlib.util
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_boundaries.py"
SPEC = importlib.util.spec_from_file_location("check_boundaries", SCRIPT)
assert SPEC and SPEC.loader
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


def write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def git_repo(path: Path) -> None:
    subprocess.run(["git", "init", "--quiet", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "add", "."], check=True)


class CheckBoundariesTests(unittest.TestCase):
    def canonical_tree(self, root: Path) -> dict[str, Path]:
        userspace = root / "userspace"
        write(userspace / "include" / "norx" / "syscall.h", b"syscall\n")
        write(userspace / "runtime" / "include" / "stddef.h", b"stddef\n")
        return CHECK.canonical_headers(userspace)

    def test_rejects_tracked_generated_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            toolchain = Path(directory) / "toolchain"
            write(toolchain / "build" / "sysroot" / "include" / "stale.h", b"stale\n")
            git_repo(toolchain)
            with self.assertRaises(CHECK.BoundaryError):
                CHECK.verify_tracked_paths(toolchain)

    def test_accepts_matching_sdk_and_rejects_stale_header(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            expected = self.canonical_tree(root)
            archive_path = root / "sdk" / "sdk.tar"
            archive_path.parent.mkdir()
            with tarfile.open(archive_path, "w") as archive:
                for relative, source in expected.items():
                    archive.add(source, f"sysroot/include/{relative}")
            self.assertEqual(CHECK.verify_sdk_archives(archive_path.parent, expected), 1)

            write(root / "userspace" / "runtime" / "include" / "stddef.h", b"stale\n")
            changed = CHECK.canonical_headers(root / "userspace")
            with self.assertRaises(CHECK.BoundaryError):
                CHECK.verify_sdk_archives(archive_path.parent, changed)

    def test_rootfs_header_tree_must_match_exactly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            expected = self.canonical_tree(root)
            staged = root / "rootfs" / "usr" / "include"
            for relative, source in expected.items():
                write(staged / relative, source.read_bytes())
            CHECK.verify_header_tree(staged, expected, "rootfs/usr/include")
            write(staged / "unexpected.h", b"extra\n")
            with self.assertRaises(CHECK.BoundaryError):
                CHECK.verify_header_tree(staged, expected, "rootfs/usr/include")

    def test_require_sdk_rejects_missing_archive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            expected = self.canonical_tree(root)
            with self.assertRaises(CHECK.BoundaryError):
                CHECK.verify_sdk_archives(root / "sdk", expected, require_archives=True)

    def test_sdk_archive_rejects_unsafe_header_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            expected = self.canonical_tree(root)
            archive_path = root / "sdk" / "sdk.tar"
            archive_path.parent.mkdir()
            with tarfile.open(archive_path, "w") as archive:
                info = tarfile.TarInfo("sysroot/include/../escape.h")
                info.size = 1
                archive.addfile(info, io.BytesIO(b"x"))
            with self.assertRaises(CHECK.BoundaryError):
                CHECK.verify_sdk_archive(archive_path, expected)


if __name__ == "__main__":
    unittest.main()
