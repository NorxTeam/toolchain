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
    cargo_command,
    checked_output,
    copy_checked,
    load_toml,
    run,
    target_emulation,
    tool_path,
    validate_elf,
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    versions = load_toml(TOOLCHAIN_ROOT / "versions.toml")
    abi = load_toml(TOOLCHAIN_ROOT / "abi.toml")
    llvm_version = versions["llvm_version"]
    rust_toolchain = versions["rust_toolchain"]
    rustup_cargo = cargo_command(rust_toolchain)
    rust_version = checked_output([*rustup_cargo[:-1], "rustc", "-Vv"])
    if versions["rustc_version"] not in rust_version or versions["rustc_commit"] not in rust_version:
        raise SystemExit(f"rustc does not match the pinned userspace toolchain:\n{rust_version}")
    ld_lld = tool_path("ld.lld.exe" if os.name == "nt" else "ld.lld", "NORX_LD_LLD")
    readobj = tool_path(
        "llvm-readobj.exe" if os.name == "nt" else "llvm-readobj", "NORX_LLVM_READOBJ"
    )
    if llvm_version not in checked_output([str(ld_lld), "--version"]):
        raise SystemExit(f"{ld_lld} is not pinned to LLVM {llvm_version}")

    manifest = REPO_ROOT / "userspace" / "rust" / "Cargo.toml"
    build_root = TOOLCHAIN_ROOT / "build" / "rust-userspace"
    rootfs = Path(os.environ.get("NORX_ROOTFS", REPO_ROOT / "norx-rootfs"))
    results: dict[str, str] = {}
    for target_name, target_info in (
        ("x86_64", abi["targets"]["x86_64"]),
        ("aarch64", abi["targets"]["aarch64"]),
    ):
        target_dir = build_root / target_name
        target_dir.mkdir(parents=True, exist_ok=True)
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
            f'target."{triple}".rustflags = ["-C", "debuginfo=2", "-L", "native={runtime_archive.parent.as_posix()}", "-l", "static=norxrt", "-C", "link-arg=-T{linker_script.as_posix()}", "-C", "link-arg=-m{target_emulation(target_name)}", "-C", "link-arg=--defsym=__nordix_linker_revision=0x{linker_revision}"]',
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
            for path in (target_dir / "cargo-target").rglob("nordix-userspace-smoke*")
            if path.is_file() and path.name in {"nordix-userspace-smoke", "nordix-userspace-smoke.exe"}
        ]
        if len(candidates) != 1:
            raise SystemExit(f"expected one Rust userspace ELF for {target_name}, found {candidates}")
        artifact = target_dir / "nordix-userspace-smoke.elf"
        copy_checked(candidates[0], artifact)
        report = validate_elf(readobj, artifact)
        symbols = checked_output([str(readobj), "--symbols", str(artifact)])
        if "_start" not in symbols:
            raise SystemExit(f"Rust userspace artifact has no _start entry for {target_name}")
        (target_dir / "readobj.txt").write_text(report, encoding="utf-8")
        destination = rootfs / "tests" / "rust" / triple / artifact.name
        copy_checked(artifact, destination)
        results[target_name] = sha256(artifact)

    manifest_dir = rootfs / "var" / "lib" / "nordix-rust"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        'schema = "nordix-rust-userspace-build"',
        "version = 1",
        f'rustc_version = "{versions["rustc_version"]}"',
        f'rustc_commit = "{versions["rustc_commit"]}"',
        'build_std = ["core", "alloc"]',
        'panic_policy = "abort"',
        'allocator = "64k_single_address_space_bump"',
        "",
    ]
    for target_name, digest in results.items():
        lines.extend([f"[targets.{target_name}]", f'userspace_smoke_sha256 = "{digest}"', ""])
    manifest_path = manifest_dir / "manifest.toml"
    manifest_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Rust userspace build passed; manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
