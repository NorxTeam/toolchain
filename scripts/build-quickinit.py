#!/usr/bin/env python3
"""Build the freestanding quickinit bootstrap ELF for the native ARM64 architecture."""

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

    manifest = REPO_ROOT / "quickinit" / "bootstrap" / "Cargo.toml"
    build_root = TOOLCHAIN_ROOT / "build" / "quickinit"
    rootfs = confined_rootfs(os.environ.get("NORX_ROOTFS"))
    results: dict[str, str] = {}
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
            "build-std=core",
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
            "--bin",
            "quickinit",
        ]
        run(command)
        candidates = [
            path
            for path in (target_dir / "cargo-target").rglob("quickinit*")
            if path.is_file() and not path.is_symlink()
            and path.parent.name == "release"
            and path.name in {"quickinit", "quickinit.exe"}
        ]
        if len(candidates) != 1:
            raise SystemExit(f"expected one quickinit ELF for {target_name}, found {candidates}")
        artifact = target_dir / "quickinit.elf"
        copy_checked(candidates[0], artifact)
        report = validate_elf(readobj, artifact, target_info)
        symbols = checked_output([str(readobj), "--symbols", str(artifact)])
        require_start_symbol(symbols, artifact)
        atomic_write_text(target_dir / "readobj.txt", report)
        destination = rootfs / "tests" / "quickinit" / triple / artifact.name
        copy_checked(artifact, destination)
        results[target_name] = sha256(artifact)

    manifest_dir = rootfs / "var" / "lib" / "nordix-quickinit"
    ensure_directory(manifest_dir)
    lines = [
        'schema = "quickinit-build"',
        "version = 1",
        f'rustc_version = "{versions["rustc_version"]}"',
        f'rustc_commit = "{versions["rustc_commit"]}"',
        'build_std = ["core"]',
        'panic_policy = "abort"',
        'bootstrap_contract = "write-getpid-wait-exit"',
        "",
    ]
    for target_name, digest in results.items():
        lines.extend([f"[targets.{target_name}]", f'quickinit_sha256 = "{digest}"', ""])
    manifest_path = manifest_dir / "manifest.toml"
    atomic_write_text(manifest_path, "\n".join(lines))
    print(f"quickinit bootstrap build passed; manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
