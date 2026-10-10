#!/usr/bin/env python3
"""Build the smallest reproducible Norx cross-toolchain smoke sysroot."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import struct
import subprocess
import sys
import tomllib


TOOLCHAIN_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = TOOLCHAIN_ROOT.parent
TOOL_PINS_PATH = TOOLCHAIN_ROOT / "toolchain-pins.toml"

ELF_HEADER = struct.Struct("<16sHHIQQQIHHHHHH")
PROGRAM_HEADER = struct.Struct("<IIQQQQQQ")
ELF_MAGIC = b"\x7fELF"
ELFCLASS64 = 2
ELFDATA2LSB = 1
EV_CURRENT = 1
ET_EXEC = 2
PT_LOAD = 1
PT_DYNAMIC = 2
PT_INTERP = 3
PT_TLS = 7
PT_GNU_STACK = 0x6474E551
PF_X = 1
PF_W = 2
PF_R = 4
ELFOSABI_NONE = 0
EM_X86_64 = 62
EM_AARCH64 = 183
PAGE_SIZE = 4096
MAX_PROGRAM_HEADERS = 128
MAX_LOAD_SEGMENTS = 16
MAX_LOAD_PAGES = 256
MAX_ELF_BYTES = 128 * 1024 * 1024
HEX_DIGEST = re.compile(r"^[0-9a-f]{64}$")
VERSION_TOKEN = re.compile(r"(?<![0-9A-Za-z])([0-9]+(?:\.[0-9]+)+)(?![0-9A-Za-z])")


@dataclass(frozen=True)
class ToolIdentity:
    name: str
    realpath: Path
    sha256: str


@dataclass(frozen=True)
class ElfSegment:
    virtual_start: int
    virtual_end: int
    file_offset: int
    file_size: int
    memory_size: int
    flags: int
    segment_type: int


@dataclass(frozen=True)
class ElfInfo:
    entry: int
    machine: int
    elf_type: int
    osabi: int
    flags: int
    segments: tuple[ElfSegment, ...]
    interpreter: bytes | None


_TOOL_IDENTITIES: dict[str, ToolIdentity] = {}
_TOOL_IDENTITIES_BY_NAME: dict[str, ToolIdentity] = {}


def load_toml(path: Path) -> dict:
    with path.open("rb") as stream:
        return tomllib.load(stream)


def load_tool_pins(path: Path = TOOL_PINS_PATH) -> dict[str, dict[str, str]]:
    try:
        _regular_file(path, "trusted tool pin manifest")
    except SystemExit:
        raise SystemExit(
            f"missing trusted tool pin manifest: {path}; "
            "provision it from the reviewed host toolchain before building"
        ) from None
    manifest = load_toml(path)
    if manifest.get("schema") != "norx-toolchain-pins" or manifest.get("version") != 1:
        raise SystemExit(f"unsupported tool pin manifest: {path}")
    tools = manifest.get("tools")
    if not isinstance(tools, dict):
        raise SystemExit(f"tool pin manifest has no [tools.*] entries: {path}")
    return tools


def _regular_file(path: Path, label: str) -> os.stat_result:
    try:
        metadata = path.lstat()
    except OSError as error:
        raise SystemExit(f"{label} is unavailable: {path}: {error}") from error
    if not stat.S_ISREG(metadata.st_mode):
        raise SystemExit(f"{label} is not a regular file: {path}")
    return metadata


def _hash_regular_file(path: Path) -> str:
    metadata = _regular_file(path, "file")
    digest = hashlib.sha256()
    descriptor: int | None = None
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino):
            raise SystemExit(f"file changed while hashing: {path}")
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
        final = os.fstat(descriptor)
        if any(
            getattr(opened, field) != getattr(final, field)
            for field in ("st_size", "st_mtime_ns", "st_ctime_ns")
        ):
            raise SystemExit(f"file changed while hashing: {path}")
    except OSError as error:
        raise SystemExit(f"cannot hash file {path}: {error}") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
    return digest.hexdigest()


def _pin_tool(name: str, candidate: Path, pin: dict[str, str]) -> Path:
    expected_realpath = pin.get("realpath")
    expected_digest = pin.get("sha256")
    if not isinstance(expected_realpath, str) or not Path(expected_realpath).is_absolute():
        raise SystemExit(f"tool pin for {name} must contain an absolute realpath")
    if (
        not isinstance(expected_digest, str)
        or expected_digest != expected_digest.lower()
        or not HEX_DIGEST.fullmatch(expected_digest)
    ):
        raise SystemExit(f"tool pin for {name} must contain a lowercase SHA-256 digest")

    try:
        realpath = candidate.resolve(strict=True)
    except OSError as error:
        raise SystemExit(f"configured {name} cannot be resolved: {candidate}: {error}") from error
    _regular_file(realpath, f"configured {name}")
    if realpath != Path(expected_realpath):
        raise SystemExit(
            f"configured {name} realpath is not pinned: {realpath}; "
            f"expected {expected_realpath}"
        )
    digest = _hash_regular_file(realpath)
    if digest != expected_digest.lower():
        raise SystemExit(
            f"configured {name} digest is not pinned: {realpath}; "
            f"got {digest}, expected {expected_digest.lower()}"
        )
    identity = ToolIdentity(name, realpath, digest)
    _TOOL_IDENTITIES[str(realpath)] = identity
    _TOOL_IDENTITIES_BY_NAME[name] = identity
    return realpath


def _tool_pin(name: str, pins: dict[str, dict[str, str]] | None) -> dict[str, str]:
    if pins is None:
        pins = load_tool_pins()
    pin = pins.get(name)
    if not isinstance(pin, dict):
        raise SystemExit(f"missing trusted pin for tool {name}")
    return pin


def verify_tool_identity(name: str) -> None:
    identity = _TOOL_IDENTITIES_BY_NAME.get(name)
    if identity is None:
        return
    current = _hash_regular_file(identity.realpath)
    if current != identity.sha256:
        raise SystemExit(f"pinned tool changed during build: {name}: {identity.realpath}")


def _verify_command_identity(command: list[str]) -> None:
    if not command:
        return
    try:
        command_path = Path(command[0]).resolve(strict=False)
    except OSError:
        return
    identity = _TOOL_IDENTITIES.get(str(command_path))
    if identity is not None:
        verify_tool_identity(identity.name)
        if identity.name == "rustup" and "run" in command:
            verify_tool_identity("cargo")
            verify_tool_identity("rustc")


def tool_path(
    name: str,
    env_name: str | None = None,
    pins: dict[str, dict[str, str]] | None = None,
) -> Path:
    pin = _tool_pin(name, pins)
    configured = os.environ.get(env_name) if env_name else None
    if configured:
        candidate = Path(configured)
    else:
        candidate = Path(pin["realpath"])
    return _pin_tool(name, candidate, pin)


def _rust_component_path(
    toolchain: str,
    component: str,
    pins: dict[str, dict[str, str]],
    env_name: str | None = None,
) -> Path:
    configured = os.environ.get(env_name) if env_name else None
    if configured:
        candidate = Path(configured)
    else:
        rustup = tool_path("rustup", "RUSTUP", pins)
        output = checked_output([str(rustup), "which", "--toolchain", toolchain, component])
        paths = [line.strip() for line in output.splitlines() if line.strip()]
        if len(paths) != 1:
            raise SystemExit(f"rustup returned an ambiguous {component} path: {output}")
        candidate = Path(paths[0])
    return _pin_tool(component, candidate, _tool_pin(component, pins))


def rust_command(
    toolchain: str, pins: dict[str, dict[str, str]] | None = None
) -> list[str]:
    pins = pins or load_tool_pins()
    return [
        str(
            _rust_component_path(
                toolchain,
                "rustc",
                pins,
                env_name="RUSTC",
            )
        )
    ]


def cargo_command(
    toolchain: str, pins: dict[str, dict[str, str]] | None = None
) -> list[str]:
    pins = pins or load_tool_pins()
    rustup = tool_path("rustup", "RUSTUP", pins)
    _rust_component_path(toolchain, "cargo", pins)
    return [str(rustup), "run", toolchain, "cargo"]


def checked_output(command: list[str]) -> str:
    _verify_command_identity(command)
    return subprocess.check_output(command, text=True, stderr=subprocess.STDOUT)


def run(
    command: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None
) -> None:
    _verify_command_identity(command)
    print("+", subprocess.list2cmdline(command))
    subprocess.run(command, cwd=cwd, check=True, env=env)


def sha256(path: Path) -> str:
    return _hash_regular_file(path)


def _open_directory(path: Path, create: bool = True) -> int | None:
    """Open a directory without following any component symlink on POSIX."""
    absolute = Path(os.path.abspath(path))
    if os.name == "nt" or os.open not in getattr(os, "supports_dir_fd", set()):
        if create:
            absolute.mkdir(parents=True, exist_ok=True)
        _assert_no_symlink_components(absolute)
        return None

    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0)
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(os.path.sep, flags | nofollow)
        for component in absolute.parts[1:]:
            while True:
                try:
                    child = os.open(component, flags | nofollow, dir_fd=descriptor)
                    break
                except FileNotFoundError:
                    if not create:
                        raise
                    try:
                        os.mkdir(component, 0o755, dir_fd=descriptor)
                    except FileExistsError:
                        continue
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException as error:
        if "descriptor" in locals():
            os.close(descriptor)
        if isinstance(error, OSError):
            raise SystemExit(f"cannot open symlink-free directory {absolute}: {error}") from error
        raise


def _assert_no_symlink_components(path: Path) -> None:
    absolute = Path(os.path.abspath(path))
    current = Path(absolute.anchor)
    for component in absolute.parts[1:]:
        current /= component
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(metadata.st_mode):
            raise SystemExit(f"symlink path component is not allowed: {current}")


def ensure_directory(path: Path) -> None:
    descriptor = _open_directory(path, create=True)
    if descriptor is not None:
        os.close(descriptor)


def confined_path(path: Path, root: Path, label: str) -> Path:
    root_real = root.resolve(strict=True)
    requested = Path(os.path.abspath(path))
    resolved = requested.resolve(strict=False)
    try:
        resolved.relative_to(root_real)
    except ValueError as error:
        raise SystemExit(f"{label} escapes its confined root {root_real}: {path}") from error
    if resolved == root_real:
        raise SystemExit(f"{label} must not be the confinement root: {path}")
    _assert_no_symlink_components(requested)
    return resolved


def confined_rootfs(configured: str | Path | None = None) -> Path:
    requested = Path(configured) if configured is not None else REPO_ROOT / "test-rootfs"
    if not requested.is_absolute():
        requested = REPO_ROOT / requested
    staging_root = REPO_ROOT / "test-rootfs"
    if Path(os.path.abspath(requested)) == staging_root:
        _assert_no_symlink_components(requested)
        rootfs = staging_root
    else:
        ensure_directory(staging_root)
        rootfs = confined_path(requested, staging_root, "rootfs")
    ensure_directory(rootfs)
    return rootfs


def _new_temp_file(parent_fd: int | None, parent: Path, prefix: str) -> tuple[int, str, Path | None]:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    for _ in range(32):
        name = f".{prefix}.{secrets.token_hex(12)}.tmp"
        try:
            if parent_fd is not None:
                descriptor = os.open(name, flags, 0o600, dir_fd=parent_fd)
                return descriptor, name, None
            path = parent / name
            descriptor = os.open(path, flags, 0o600)
            return descriptor, name, path
        except FileExistsError:
            continue
    raise SystemExit(f"could not allocate a temporary publication file in {parent}")


def _fsync_directory(descriptor: int | None) -> None:
    if descriptor is None:
        return
    try:
        os.fsync(descriptor)
    except OSError as error:
        raise SystemExit(f"could not sync publication directory: {error}") from error


def _publish_bytes(data: bytes, destination: Path, mode: int = 0o644) -> None:
    parent = destination.parent
    ensure_directory(parent)
    parent_fd = _open_directory(parent, create=False)
    temp_fd: int | None = None
    temp_name: str | None = None
    temp_path: Path | None = None
    try:
        try:
            existing = (
                os.stat(destination.name, dir_fd=parent_fd, follow_symlinks=False)
                if parent_fd is not None
                else destination.lstat()
            )
            if stat.S_ISLNK(existing.st_mode) or not stat.S_ISREG(existing.st_mode):
                raise SystemExit(f"destination is not a replaceable regular file: {destination}")
        except FileNotFoundError:
            pass
        temp_fd, temp_name, temp_path = _new_temp_file(parent_fd, parent, destination.name)
        view = memoryview(data)
        while view:
            written = os.write(temp_fd, view)
            if written <= 0:
                raise SystemExit(f"short write while publishing {destination}")
            view = view[written:]
        os.fchmod(temp_fd, mode & 0o7777)
        os.fsync(temp_fd)
        os.close(temp_fd)
        temp_fd = None
        if parent_fd is not None:
            os.replace(temp_name, destination.name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
        else:
            os.replace(temp_path, destination)
        temp_name = None
        temp_path = None
        _fsync_directory(parent_fd)
    finally:
        if temp_fd is not None:
            os.close(temp_fd)
        if temp_name is not None:
            try:
                if parent_fd is not None:
                    os.unlink(temp_name, dir_fd=parent_fd)
                elif temp_path is not None:
                    temp_path.unlink()
            except FileNotFoundError:
                pass
        if parent_fd is not None:
            os.close(parent_fd)


def atomic_write_text(destination: Path, text: str) -> None:
    _publish_bytes(text.encode("utf-8"), destination)


def atomic_write_bytes(destination: Path, data: bytes, mode: int = 0o644) -> None:
    _publish_bytes(data, destination, mode)


def copy_checked(source: Path, destination: Path) -> None:
    source_metadata = _regular_file(source, "source")
    ensure_directory(destination.parent)
    parent_fd = _open_directory(destination.parent, create=False)
    source_fd: int | None = None
    temp_fd: int | None = None
    temp_name: str | None = None
    temp_path: Path | None = None
    copied_digest = hashlib.sha256()
    try:
        source_flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        source_fd = os.open(source, source_flags)
        opened_metadata = os.fstat(source_fd)
        if not stat.S_ISREG(opened_metadata.st_mode):
            raise SystemExit(f"source is not a regular file: {source}")
        if opened_metadata.st_dev != source_metadata.st_dev or opened_metadata.st_ino != source_metadata.st_ino:
            raise SystemExit(f"source changed while opening: {source}")
        try:
            existing = (
                os.stat(destination.name, dir_fd=parent_fd, follow_symlinks=False)
                if parent_fd is not None
                else destination.lstat()
            )
            if stat.S_ISLNK(existing.st_mode) or not stat.S_ISREG(existing.st_mode):
                raise SystemExit(f"destination is not a replaceable regular file: {destination}")
        except FileNotFoundError:
            pass
        temp_fd, temp_name, temp_path = _new_temp_file(parent_fd, destination.parent, destination.name)
        while True:
            chunk = os.read(source_fd, 1024 * 1024)
            if not chunk:
                break
            copied_digest.update(chunk)
            view = memoryview(chunk)
            while view:
                written = os.write(temp_fd, view)
                if written <= 0:
                    raise SystemExit(f"short write while publishing {destination}")
                view = view[written:]
        final_metadata = os.fstat(source_fd)
        stable_fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        if any(getattr(opened_metadata, field) != getattr(final_metadata, field) for field in stable_fields):
            raise SystemExit(f"source changed while copying: {source}")
        os.fchmod(temp_fd, stat.S_IMODE(opened_metadata.st_mode))
        os.fsync(temp_fd)
        os.close(temp_fd)
        temp_fd = None
        if parent_fd is not None:
            os.replace(temp_name, destination.name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
        else:
            os.replace(temp_path, destination)
        temp_name = None
        temp_path = None
        _fsync_directory(parent_fd)
        destination_fd = (
            os.open(destination.name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=parent_fd)
            if parent_fd is not None
            else os.open(destination, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        )
        try:
            destination_digest = hashlib.sha256()
            while True:
                chunk = os.read(destination_fd, 1024 * 1024)
                if not chunk:
                    break
                destination_digest.update(chunk)
        finally:
            os.close(destination_fd)
        if destination_digest.digest() != copied_digest.digest():
            raise SystemExit(f"published file differs: {source} -> {destination}")
    finally:
        if source_fd is not None:
            os.close(source_fd)
        if temp_fd is not None:
            os.close(temp_fd)
        if temp_name is not None:
            try:
                if parent_fd is not None:
                    os.unlink(temp_name, dir_fd=parent_fd)
                elif temp_path is not None:
                    temp_path.unlink()
            except FileNotFoundError:
                pass
        if parent_fd is not None:
            os.close(parent_fd)


def stage_userspace_headers(sysroot: Path, rootfs: Path) -> None:
    for source_root in (
        REPO_ROOT / "userspace" / "include",
        REPO_ROOT / "userspace" / "runtime" / "include",
    ):
        for source in source_root.rglob("*"):
            if not source.is_file():
                continue
            relative = source.relative_to(source_root)
            copy_checked(source, sysroot / "include" / relative)
            copy_checked(source, rootfs / "usr" / "include" / relative)


def _machine_number(name: str | None) -> int | None:
    return {"EM_X86_64": EM_X86_64, "EM_AARCH64": EM_AARCH64}.get(name or "")


def parse_elf(data: bytes, artifact: Path, target_info: dict | None = None) -> ElfInfo:
    if len(data) > MAX_ELF_BYTES or len(data) < ELF_HEADER.size:
        raise SystemExit(f"{artifact} is truncated or exceeds the ELF size limit")
    (
        ident,
        elf_type,
        machine,
        version,
        entry,
        program_header_offset,
        section_header_offset,
        flags,
        header_size,
        program_header_size,
        program_header_count,
        section_header_size,
        section_header_count,
        section_name_index,
    ) = ELF_HEADER.unpack_from(data)
    if ident[:4] != ELF_MAGIC or ident[4] != ELFCLASS64 or ident[5] != ELFDATA2LSB:
        raise SystemExit(f"{artifact} is not little-endian ELF64")
    if ident[6] != EV_CURRENT or ident[7] != ELFOSABI_NONE or ident[8] != 0:
        raise SystemExit(f"{artifact} has an unsupported ELF ABI identity")
    if version != EV_CURRENT or elf_type != ET_EXEC or header_size != ELF_HEADER.size:
        raise SystemExit(f"{artifact} has an unsupported ELF header")
    if program_header_size != PROGRAM_HEADER.size or not 0 < program_header_count <= MAX_PROGRAM_HEADERS:
        raise SystemExit(f"{artifact} has invalid program-header sizing")
    machine_expected = _machine_number((target_info or {}).get("machine"))
    if machine_expected is not None and machine != machine_expected:
        raise SystemExit(f"{artifact} has machine {machine}, expected {machine_expected}")
    expected_flags = (target_info or {}).get("elf_flags", 0)
    if flags != expected_flags:
        raise SystemExit(f"{artifact} has ELF flags {flags:#x}, expected {expected_flags:#x}")
    expected_osabi = (target_info or {}).get("elf_osabi", ELFOSABI_NONE)
    if expected_osabi != ident[7]:
        raise SystemExit(f"{artifact} has ELF OSABI {ident[7]}, expected {expected_osabi}")
    ph_end = program_header_offset + program_header_size * program_header_count
    if ph_end < program_header_offset or ph_end > len(data):
        raise SystemExit(f"{artifact} has program headers outside the file")
    if section_header_count:
        if section_header_size == 0 or section_header_offset + section_header_size * section_header_count > len(data):
            raise SystemExit(f"{artifact} has section headers outside the file")
        if section_name_index >= section_header_count:
            raise SystemExit(f"{artifact} has an invalid section-name index")
    elif section_name_index != 0:
        raise SystemExit(f"{artifact} has a section-name index without sections")

    page_size = int((target_info or {}).get("page_size", PAGE_SIZE))
    if page_size != PAGE_SIZE or not page_size > 0 or not (page_size & (page_size - 1)) == 0:
        raise SystemExit(f"{artifact} has an unsupported page size contract")
    expected_base = (target_info or {}).get("image_base")
    expected_limit = (target_info or {}).get("user_limit")
    segments: list[ElfSegment] = []
    interpreter: bytes | None = None
    for index in range(program_header_count):
        offset = program_header_offset + index * program_header_size
        segment_type, segment_flags, file_offset, virtual_address, _, file_size, memory_size, alignment = PROGRAM_HEADER.unpack_from(data, offset)
        file_end = file_offset + file_size
        if file_end < file_offset or file_end > len(data) or file_size > memory_size:
            raise SystemExit(f"{artifact} has an invalid program-header file range")
        # lld emits an empty PT_TLS when the shared script has no TLS input.
        # The file-size check above requires this harmless header to be empty.
        if segment_type == PT_LOAD and memory_size == 0:
            raise SystemExit(f"{artifact} has an empty loadable segment")
        if segment_type == PT_LOAD:
            if segment_flags & ~0x7 or not segment_flags & PF_R or segment_flags & PF_W and segment_flags & PF_X:
                raise SystemExit(f"{artifact} has invalid or W+X PT_LOAD permissions")
            if alignment != page_size or virtual_address % page_size != 0 or file_offset % page_size != virtual_address % page_size:
                raise SystemExit(f"{artifact} has an invalid PT_LOAD alignment")
            virtual_end = virtual_address + memory_size
            if virtual_end < virtual_address or virtual_end > (1 << 64):
                raise SystemExit(f"{artifact} has an overflowing PT_LOAD address range")
            if expected_base is not None and virtual_address < expected_base:
                raise SystemExit(f"{artifact} loads below its ABI image base")
            if expected_limit is not None and virtual_end > expected_limit:
                raise SystemExit(f"{artifact} loads above its ABI user limit")
            segments.append(
                ElfSegment(
                    virtual_address,
                    virtual_end,
                    file_offset,
                    file_size,
                    memory_size,
                    segment_flags,
                    segment_type,
                )
            )
        elif segment_type == PT_INTERP:
            if interpreter is not None or file_size == 0 or file_size > 4096:
                raise SystemExit(f"{artifact} has an invalid interpreter segment")
            raw = data[file_offset:file_end]
            nul = raw.find(b"\0")
            if nul < 1 or any(raw[nul + 1 :]):
                raise SystemExit(f"{artifact} has an invalid interpreter path")
            interpreter = raw[:nul]
        elif segment_type == PT_DYNAMIC:
            raise SystemExit(f"{artifact} is dynamically linked; static ELF is required")
        elif segment_type == PT_GNU_STACK and segment_flags & PF_X:
            raise SystemExit(f"{artifact} requests an executable stack")
        elif segment_type == PT_TLS and alignment and alignment & (alignment - 1):
            raise SystemExit(f"{artifact} has an invalid PT_TLS alignment")
    if interpreter is not None:
        raise SystemExit(f"{artifact} contains PT_INTERP; static Norx images must not have an interpreter")
    if not segments or len(segments) > MAX_LOAD_SEGMENTS:
        raise SystemExit(f"{artifact} has an invalid number of PT_LOAD segments")
    segments.sort(key=lambda segment: segment.virtual_start)
    total_pages = 0
    for previous, current in zip(segments, segments[1:]):
        if current.virtual_start < previous.virtual_end:
            raise SystemExit(f"{artifact} has overlapping PT_LOAD segments")
    for segment in segments:
        aligned_end = (segment.virtual_end + page_size - 1) & ~(page_size - 1)
        total_pages += (aligned_end - segment.virtual_start) // page_size
    if total_pages > MAX_LOAD_PAGES:
        raise SystemExit(f"{artifact} has too many loadable pages")
    entry_segment = next(
        (
            segment
            for segment in segments
            if segment.virtual_start <= entry < segment.virtual_end
            and entry < segment.virtual_start + segment.file_size
            and segment.flags & PF_X
        ),
        None,
    )
    if entry_segment is None:
        raise SystemExit(f"{artifact} entry is not in file-backed executable code")
    return ElfInfo(entry, machine, elf_type, ident[7], flags, tuple(segments), interpreter)


def _read_elf(artifact: Path) -> bytes:
    metadata = _regular_file(artifact, "ELF artifact")
    if metadata.st_size > MAX_ELF_BYTES:
        raise SystemExit(f"ELF artifact exceeds the size limit: {artifact}")
    descriptor: int | None = None
    try:
        descriptor = os.open(
            artifact,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino):
            raise SystemExit(f"ELF artifact changed while opening: {artifact}")
        data = bytearray()
        while len(data) <= MAX_ELF_BYTES:
            chunk = os.read(descriptor, min(1024 * 1024, MAX_ELF_BYTES + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
        final = os.fstat(descriptor)
        if any(
            getattr(opened, field) != getattr(final, field)
            for field in ("st_size", "st_mtime_ns", "st_ctime_ns")
        ):
            raise SystemExit(f"ELF artifact changed while reading: {artifact}")
    except OSError as error:
        raise SystemExit(f"cannot read ELF artifact {artifact}: {error}") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if len(data) != metadata.st_size:
        raise SystemExit(f"ELF artifact changed while reading: {artifact}")
    return bytes(data)


def validate_elf(readobj: Path | None, artifact: Path, target_info: dict | None = None) -> str:
    info = parse_elf(_read_elf(artifact), artifact, target_info)
    if readobj is None:
        return ""
    return checked_output(
        [str(readobj), "--file-headers", "--sections", "--program-headers", str(artifact)]
    )


def require_start_symbol(report: str, artifact: Path, entry: int | None = None) -> None:
    for line in report.splitlines():
        fields = line.replace("|", " ").split()
        if "_start" not in fields:
            continue
        if entry is None:
            return
        try:
            if int(fields[0], 16) == entry:
                return
        except (ValueError, IndexError):
            continue
    raise SystemExit(f"{artifact} has no exact _start symbol at its ELF entry")


def require_llvm_version(tool: Path, expected: str) -> str:
    output = checked_output([str(tool), "--version"])
    versions = VERSION_TOKEN.findall(output)
    if expected not in versions:
        raise SystemExit(f"{tool} version is not exactly pinned to LLVM {expected}: {output}")
    return output


def require_rust_version(tool: list[str], versions: dict) -> str:
    verify_tool_identity("rustc")
    output = checked_output([*tool, "-Vv"])
    verify_tool_identity("rustc")
    fields = {
        key.strip(): value.strip()
        for line in output.splitlines()
        if ":" in line
        for key, value in [line.split(":", 1)]
    }
    if fields.get("release") != versions["rustc_version"] or fields.get("commit-hash") != versions["rustc_commit"]:
        raise SystemExit(f"rustc does not match the exact toolchain pin:\n{output}")
    return output


def target_flags(target_name: str) -> list[str]:
    if target_name == "aarch64":
        return ["-mgeneral-regs-only"]
    raise SystemExit(f"unsupported Norx target: {target_name}")


def target_emulation(target_name: str) -> str:
    return {"aarch64": "aarch64elf"}[target_name]


def build_target(
    *,
    target_name: str,
    target_info: dict,
    clang: Path,
    ld_lld: Path,
    readobj: Path,
    objdump: Path,
    cargo: list[str],
    output_root: Path,
    sysroot: Path,
) -> dict[str, str]:
    target_dir = output_root / target_name
    ensure_directory(target_dir)
    include_dir = sysroot / "include"
    fixture_c = TOOLCHAIN_ROOT / "fixtures" / "hello.c"
    linker_script = TOOLCHAIN_ROOT / target_info["linker_script"]

    c_object = target_dir / "hello-c.o"
    c_elf = target_dir / "hello-c.elf"
    rust_elf = target_dir / "hello-rust.elf"
    rust_target = TOOLCHAIN_ROOT / "targets" / f"{target_name}-unknown-norx.json"
    linker_revision = hashlib.sha256(linker_script.read_bytes()).hexdigest()[:16]

    clang_command = [
        str(clang),
        f"--target={target_info['triple']}",
        "-std=c11",
        "-ffreestanding",
        "-fno-builtin",
        "-fno-stack-protector",
        "-fno-unwind-tables",
        "-fno-asynchronous-unwind-tables",
        "-g",
        "-nostdinc",
        "-isystem",
        str(include_dir),
        *target_flags(target_name),
        "-c",
        str(fixture_c),
        "-o",
        str(c_object),
    ]
    run(clang_command)

    run(
        [
            str(ld_lld),
            "-m",
            target_emulation(target_name),
            "-T",
            str(linker_script),
            "--no-dynamic-linker",
            "-z",
            "max-page-size=0x1000",
            "-o",
            str(c_elf),
            str(c_object),
        ]
    )

    cargo_target_dir = target_dir / "cargo-target"
    target_triple = target_info["triple"]
    cargo_config = [
        "--config",
        f'target."{target_triple}".linker = "{ld_lld.as_posix()}"',
        "--config",
        f'target."{target_triple}".rustflags = ["-C", "debuginfo=2", "-C", "link-arg=-T{linker_script.as_posix()}", "-C", "link-arg=-m{target_emulation(target_name)}", "-C", "link-arg=--defsym=__linker_revision=0x{linker_revision}"]',
    ]
    cargo_command_line = [
        *cargo,
        *cargo_config,
        "build",
        "-Z",
        "build-std=core",
        "-Z",
        "json-target-spec",
        "--offline",
        "--manifest-path",
        str(TOOLCHAIN_ROOT / "fixtures" / "Cargo.toml"),
        "--target",
        str(rust_target),
        "--target-dir",
        str(cargo_target_dir),
        "--release",
    ]
    run(cargo_command_line)
    rust_candidates = []
    for path in cargo_target_dir.rglob("norx-hello*"):
        if path.name not in {"norx-hello", "norx-hello.exe"}:
            continue
        try:
            if stat.S_ISREG(path.lstat().st_mode):
                rust_candidates.append(path)
        except FileNotFoundError:
            continue
    if len(rust_candidates) != 1:
        raise SystemExit(f"expected one Rust ELF output, found: {rust_candidates}")
    copy_checked(rust_candidates[0], rust_elf)

    reports = {
        "c": validate_elf(readobj, c_elf, target_info),
        "rust": validate_elf(readobj, rust_elf, target_info),
    }
    for language, report in reports.items():
        atomic_write_text(target_dir / f"hello-{language}.readobj.txt", report)
        artifact = target_dir / f"hello-{language}.elf"
        entry = parse_elf(_read_elf(artifact), artifact, target_info).entry
        symbols = checked_output([str(objdump), "--syms", str(artifact)])
        require_start_symbol(symbols, artifact, entry)
        atomic_write_text(target_dir / f"hello-{language}.symbols.txt", symbols)

    return {
        "c": str(c_elf),
        "rust": str(rust_elf),
        "c_sha256": sha256(c_elf),
        "rust_sha256": sha256(rust_elf),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=TOOLCHAIN_ROOT / "build",
        help="toolchain build output directory",
    )
    args = parser.parse_args()

    versions = load_toml(TOOLCHAIN_ROOT / "versions.toml")
    abi = load_toml(TOOLCHAIN_ROOT / "abi.toml")
    pins = load_tool_pins()
    llvm_version = versions["llvm_version"]
    clang = tool_path("clang", "NORX_CLANG", pins)
    ld_lld = tool_path("ld_lld", "NORX_LD_LLD", pins)
    readobj = tool_path("llvm_readobj", "NORX_LLVM_READOBJ", pins)
    objdump = tool_path("llvm_objdump", "NORX_LLVM_OBJDUMP", pins)
    for tool in (clang, ld_lld, readobj, objdump):
        require_llvm_version(tool, llvm_version)

    rustc = rust_command(versions["rust_toolchain"], pins)
    cargo = cargo_command(versions["rust_toolchain"], pins)
    require_rust_version(rustc, versions)

    sysroot = TOOLCHAIN_ROOT / "build" / "sysroot"
    rootfs = confined_rootfs(os.environ.get("NORX_ROOTFS"))
    stage_userspace_headers(sysroot, rootfs)

    build_root = TOOLCHAIN_ROOT / "build"
    ensure_directory(build_root)
    if Path(os.path.abspath(args.out)) == build_root:
        output_root = build_root
    else:
        output_root = confined_path(args.out, build_root, "build output")
    ensure_directory(output_root)
    results = {}
    for target_name, target_info in (
        ("aarch64", abi["targets"]["aarch64"]),
    ):
        results[target_name] = build_target(
            target_name=target_name,
            target_info=target_info,
            clang=clang,
            ld_lld=ld_lld,
            readobj=readobj,
            objdump=objdump,
            cargo=cargo,
            output_root=output_root,
            sysroot=sysroot,
        )
        for language in ("c", "rust"):
            artifact = Path(results[target_name][language])
            copy_checked(
                artifact,
                rootfs / "tests" / "toolchain" / target_name / artifact.name,
            )

    manifest_dir = rootfs / "var" / "lib" / "norx-toolchain"
    ensure_directory(manifest_dir)
    manifest_lines = [
        'schema = "norx-toolchain-build"',
        "version = 2",
        f'llvm_version = "{llvm_version}"',
        f'rustc_version = "{versions["rustc_version"]}"',
        f'rustc_commit = "{versions["rustc_commit"]}"',
        f'abi_version = {abi["version"]}',
        "",
    ]
    for name in sorted(_TOOL_IDENTITIES_BY_NAME):
        identity = _TOOL_IDENTITIES_BY_NAME[name]
        manifest_lines.extend(
            [
                f"[tools.{name}]",
                f"realpath = {json.dumps(str(identity.realpath))}",
                f"sha256 = {json.dumps(identity.sha256)}",
                "",
            ]
        )
    for target_name, target_results in results.items():
        manifest_lines.extend(
            [
                f"[targets.{target_name}]",
                f'c_sha256 = "{target_results["c_sha256"]}"',
                f'rust_sha256 = "{target_results["rust_sha256"]}"',
                "",
            ]
        )
    manifest_path = manifest_dir / "manifest.toml"
    atomic_write_text(manifest_path, "\n".join(manifest_lines))
    print(f"toolchain smoke build passed; manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
