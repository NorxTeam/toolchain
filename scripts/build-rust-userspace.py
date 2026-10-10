#!/usr/bin/env python3
"""Build the target-owned Rust core/alloc userspace API and smoke binary."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import sys

SCRIPT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_ROOT))
from build import (  # noqa: E402
    REPO_ROOT,
    TOOLCHAIN_ROOT,
    atomic_write_text,
    cargo_command,
    checked_output,
    confined_rootfs,
    copy_checked,
    ensure_directory,
    load_tool_pins,
    load_toml,
    require_llvm_version,
    require_rust_version,
    require_start_symbol,
    run,
    rust_command,
    target_emulation,
    tool_path,
    validate_elf,
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    versions = load_toml(TOOLCHAIN_ROOT / "versions.toml")
    abi = load_toml(TOOLCHAIN_ROOT / "abi.toml")
    pins = load_tool_pins()
    llvm_version = versions["llvm_version"]
    rust_toolchain = versions["rust_toolchain"]
    rustup_cargo = cargo_command(rust_toolchain, pins)
    require_rust_version(rust_command(rust_toolchain, pins), versions)
    ld_lld = tool_path("ld_lld", "NORX_LD_LLD", pins)
    readobj = tool_path("llvm_readobj", "NORX_LLVM_READOBJ", pins)
    require_llvm_version(ld_lld, llvm_version)

    manifest = REPO_ROOT / "userspace" / "rust" / "Cargo.toml"
    build_root = TOOLCHAIN_ROOT / "build" / "rust-userspace"
    nsh_manifest = REPO_ROOT / "nsh" / "Cargo.toml"
    nsh_build_root = TOOLCHAIN_ROOT / "build" / "nsh"
    rootfs = confined_rootfs(os.environ.get("NORX_ROOTFS"))
    results: dict[str, str] = {}
    nsh_results: dict[str, str] = {}
    for target_name, target_info in (
        ("aarch64", abi["targets"]["aarch64"]),
    ):
        target_dir = build_root / target_name
        ensure_directory(target_dir)
        linker_script = TOOLCHAIN_ROOT / target_info["linker_script"]
        target_spec = TOOLCHAIN_ROOT / "targets" / f"{target_name}-unknown-norx.json"
        triple = target_info["triple"]
        runtime_archive = TOOLCHAIN_ROOT / "build" / "runtime" / target_name / "libnorxrt.a"
        linker_revision = sha256(linker_script)[:16]
        if not runtime_archive.is_file():
            raise SystemExit(
                f"missing target runtime archive: {runtime_archive}; run build-runtime.py first"
            )
        config = [
            "--config",
            f'target."{triple}".linker = "{ld_lld.as_posix()}"',
            "--config",
            f'target."{triple}".rustflags = ["-C", "debuginfo=2", "-L", "native={runtime_archive.parent.as_posix()}", "-l", "static=norxrt", "-C", "link-arg=-T{linker_script.as_posix()}", "-C", "link-arg=-m{target_emulation(target_name)}", "-C", "link-arg=--defsym=__linker_revision=0x{linker_revision}"]',
        ]
        command = [
            *rustup_cargo,
            *config,
            "build",
            "-Z",
            "build-std=core,alloc",
            "-Z",
            "json-target-spec",
            "--offline",
            "--locked",
            "--manifest-path",
            str(manifest),
            "--target",
            str(target_spec),
            "--target-dir",
            str(target_dir / "cargo-target"),
            "--release",
        ]
        run(command)
        candidates = [
            path
            for path in (target_dir / "cargo-target").rglob("userspace-smoke*")
            if path.is_file() and not path.is_symlink()
            and path.parent.name == "release"
            and path.name in {"userspace-smoke", "userspace-smoke.exe"}
        ]
        if len(candidates) != 1:
            raise SystemExit(f"expected one Rust userspace ELF for {target_name}, found {candidates}")
        artifact = target_dir / "userspace-smoke.elf"
        copy_checked(candidates[0], artifact)
        report = validate_elf(readobj, artifact, target_info)
        symbols = checked_output([str(readobj), "--symbols", str(artifact)])
        require_start_symbol(symbols, artifact)
        atomic_write_text(target_dir / "readobj.txt", report)
        destination = rootfs / "tests" / "rust" / triple / artifact.name
        copy_checked(artifact, destination)
        results[target_name] = sha256(artifact)

        nsh_target_dir = nsh_build_root / target_name
        ensure_directory(nsh_target_dir)
        nsh_config = [
            "--config",
            f'target."{triple}".linker = "{ld_lld.as_posix()}"',
            "--config",
            f'target."{triple}".rustflags = ["-C", "debuginfo=2", "-L", "native={runtime_archive.parent.as_posix()}", "-l", "static=norxrt", "-C", "link-arg=-T{linker_script.as_posix()}", "-C", "link-arg=-m{target_emulation(target_name)}", "-C", "link-arg=--defsym=__linker_revision=0x{linker_revision}"]',
        ]
        nsh_command = [
            *rustup_cargo,
            *nsh_config,
            "build",
            "-Z",
            "build-std=core,alloc",
            "-Z",
            "json-target-spec",
            "--offline",
            "--locked",
            "--manifest-path",
            str(nsh_manifest),
            "--target",
            str(target_spec),
            "--target-dir",
            str(nsh_target_dir / "cargo-target"),
            "--release",
            "--features",
            "norx-target",
            "--bin",
            "nsh",
        ]
        run(nsh_command)
        nsh_candidates = [
            path
            for path in (nsh_target_dir / "cargo-target").rglob("nsh*")
            if path.is_file() and not path.is_symlink()
            and path.parent.name == "release"
            and path.name in {"nsh", "nsh.exe"}
        ]
        if len(nsh_candidates) != 1:
            raise SystemExit(f"expected one nsh ELF for {target_name}, found {nsh_candidates}")
        nsh_artifact = nsh_target_dir / "nsh.elf"
        copy_checked(nsh_candidates[0], nsh_artifact)
        nsh_report = validate_elf(readobj, nsh_artifact, target_info)
        nsh_symbols = checked_output([str(readobj), "--symbols", str(nsh_artifact)])
        require_start_symbol(nsh_symbols, nsh_artifact)
        atomic_write_text(nsh_target_dir / "readobj.txt", nsh_report)
        nsh_destination = rootfs / "tests" / "nsh" / triple / nsh_artifact.name
        copy_checked(nsh_artifact, nsh_destination)
        nsh_results[target_name] = sha256(nsh_artifact)

    manifest_dir = rootfs / "var" / "lib" / "rust"
    ensure_directory(manifest_dir)
    lines = [
        'schema = "rust-userspace-build"',
        "version = 1",
        f'rustc_version = "{versions["rustc_version"]}"',
        f'rustc_commit = "{versions["rustc_commit"]}"',
        'build_std = ["core", "alloc"]',
        'panic_policy = "abort"',
        'allocator = "256k_single_address_space_bump"',
        "",
    ]
    for target_name, digest in results.items():
        lines.extend(
            [
                f"[targets.{target_name}]",
                f'userspace_smoke_sha256 = "{digest}"',
                f'nsh_sha256 = "{nsh_results[target_name]}"',
                "",
            ]
        )
    manifest_path = manifest_dir / "manifest.toml"
    atomic_write_text(manifest_path, "\n".join(lines))
    print(f"Rust userspace build passed; manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
