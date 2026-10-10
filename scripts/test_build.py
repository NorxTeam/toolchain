#!/usr/bin/env python3
"""Focused no-framework regression tests for the build trust boundary."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build  # noqa: E402


TARGET = {
    "machine": "EM_X86_64",
    "elf_osabi": 0,
    "elf_flags": 0,
    "page_size": 4096,
    "image_base": 0x400000000000,
    "user_limit": 0x0000800000000000,
}


def image(
    *,
    machine: int = build.EM_X86_64,
    flags: int = build.PF_R | build.PF_X,
    entry: int = 0x400000000100,
    second_header: tuple[int, int, int, int, int, int, int, int] | None = None,
) -> bytes:
    data = bytearray(build.PAGE_SIZE)
    ident = bytearray(16)
    ident[:4] = build.ELF_MAGIC
    ident[4] = build.ELFCLASS64
    ident[5] = build.ELFDATA2LSB
    ident[6] = build.EV_CURRENT
    ident[7] = build.ELFOSABI_NONE
    header = build.ELF_HEADER.pack(
        bytes(ident),
        build.ET_EXEC,
        machine,
        build.EV_CURRENT,
        entry,
        build.ELF_HEADER.size,
        0,
        0,
        build.ELF_HEADER.size,
        build.PROGRAM_HEADER.size,
        1 if second_header is None else 2,
        0,
        0,
        0,
    )
    data[: len(header)] = header
    program = build.PROGRAM_HEADER.pack(
        build.PT_LOAD,
        flags,
        0,
        0x400000000000,
        0x400000000000,
        build.PAGE_SIZE,
        build.PAGE_SIZE,
        build.PAGE_SIZE,
    )
    data[build.ELF_HEADER.size : build.ELF_HEADER.size + len(program)] = program
    if second_header is not None:
        offset = build.ELF_HEADER.size + build.PROGRAM_HEADER.size
        data[offset : offset + build.PROGRAM_HEADER.size] = build.PROGRAM_HEADER.pack(
            *second_header
        )
    return bytes(data)


class BuildBoundaryTests(unittest.TestCase):
    def assert_rejected(self, function, *args) -> None:
        with self.assertRaises(SystemExit):
            function(*args)

    def test_valid_static_elf_and_target_contract(self) -> None:
        info = build.parse_elf(image(), Path("valid.elf"), TARGET)
        self.assertEqual(info.machine, build.EM_X86_64)
        self.assertEqual(info.entry, 0x400000000100)
        self.assertIsNone(info.interpreter)

    def test_elf_rejects_identity_permissions_interpreter_and_entry_errors(self) -> None:
        self.assert_rejected(build.parse_elf, image(machine=build.EM_AARCH64), Path("bad.elf"), TARGET)
        self.assert_rejected(
            build.parse_elf,
            image(flags=build.PF_R | build.PF_W | build.PF_X),
            Path("w+x.elf"),
            TARGET,
        )
        interp = (build.PT_INTERP, 4, 0x300, 0, 0, 5, 5, 1)
        self.assert_rejected(build.parse_elf, image(second_header=interp), Path("interp.elf"), TARGET)
        self.assert_rejected(
            build.parse_elf,
            image(entry=0x400000001000),
            Path("entry.elf"),
            TARGET,
        )

    def test_truncated_and_random_headers_never_escape_as_python_errors(self) -> None:
        valid = image()
        for length in range(len(valid) + 1):
            try:
                build.parse_elf(valid[:length], Path("truncated.elf"), TARGET)
            except SystemExit:
                pass
        for seed in range(128):
            malformed = bytes((index * 37 + seed) & 0xFF for index in range(seed % 97))
            try:
                build.parse_elf(malformed, Path("fuzz.elf"), TARGET)
            except SystemExit:
                pass

    def test_version_rejects_substring_and_symbol_rejects_prefix(self) -> None:
        with patch.object(build, "checked_output", return_value="clang version 122.1.7"):
            self.assert_rejected(build.require_llvm_version, Path("clang"), "22.1.7")
        self.assert_rejected(build.require_start_symbol, "0001 _start_helper", Path("bad.elf"))
        build.require_start_symbol("0001 g F .text 0004 _start", Path("good.elf"), 1)

    def test_tool_identity_requires_exact_realpath_and_digest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary).resolve() / "tool"
            path.write_bytes(b"trusted tool")
            pin = {
                "realpath": str(path.resolve()),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            previous = os.environ.get("NORX_TEST_TOOL")
            os.environ["NORX_TEST_TOOL"] = str(path)
            try:
                self.assertEqual(build.tool_path("test", "NORX_TEST_TOOL", {"test": pin}), path)
                path.write_bytes(b"changed tool")
                self.assert_rejected(build.tool_path, "test", "NORX_TEST_TOOL", {"test": pin})
            finally:
                if previous is None:
                    os.environ.pop("NORX_TEST_TOOL", None)
                else:
                    os.environ["NORX_TEST_TOOL"] = previous

    def test_copy_is_atomic_and_rejects_symlink_targets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            source = root / "source"
            source.write_bytes(b"new contents")
            destination = root / "nested" / "output"
            build.copy_checked(source, destination)
            self.assertEqual(destination.read_bytes(), b"new contents")
            outside = root / "outside"
            outside.write_bytes(b"must survive")
            destination.unlink()
            destination.symlink_to(outside)
            self.assert_rejected(build.copy_checked, source, destination)
            self.assertEqual(outside.read_bytes(), b"must survive")
            symlink_parent = root / "link-parent"
            symlink_parent.symlink_to(root)
            self.assert_rejected(build.copy_checked, source, symlink_parent / "escaped")

    def test_rootfs_is_repository_confined_and_symlink_free(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            confined = root / "confined"
            confined.mkdir()
            self.assert_rejected(build.confined_path, root / "outside", confined, "rootfs")
            symlink = root / "link"
            symlink.symlink_to(root)
            self.assert_rejected(build.confined_path, symlink / "rootfs", confined, "rootfs")


if __name__ == "__main__":
    unittest.main()
