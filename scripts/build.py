#!/usr/bin/env python3
"""Build the smallest reproducible Norx cross-toolchain smoke sysroot."""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib


TOOLCHAIN_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = TOOLCHAIN_ROOT.parent


def load_toml(path: Path) -> dict:
    with path.open("rb") as stream:
        return tomllib.load(stream)


def tool_path(name: str, env_name: str | None = None) -> Path:
    configured = os.environ.get(env_name) if env_name else None
    if configured:
        candidate = Path(configured)
        if candidate.is_file():
            return candidate
        raise SystemExit(f"configured tool does not exist: {candidate}")

    found = shutil.which(name)
    if found:
        return Path(found)

    if os.name == "nt":
        candidate = Path(r"C:\Program Files\LLVM\bin") / name
        if candidate.is_file():
            return candidate

    raise SystemExit(f"required host tool is not on PATH: {name}")


def rust_command(toolchain: str) -> list[str]:
    configured = os.environ.get("RUSTC")
    if configured:
        candidate = Path(configured)
        if not candidate.is_file():
            raise SystemExit(f"configured RUSTC does not exist: {candidate}")
        return [str(candidate)]

    rustup = shutil.which("rustup")
    if not rustup:
        raise SystemExit("rustup is required to select the pinned Rust toolchain")
    return [rustup, "run", toolchain, "rustc"]


def cargo_command(toolchain: str) -> list[str]:
    rustup = shutil.which("rustup")
    if not rustup:
        raise SystemExit("rustup is required to select the pinned Cargo toolchain")
    return [rustup, "run", toolchain, "cargo"]


def checked_output(command: list[str]) -> str:
    return subprocess.check_output(command, text=True, stderr=subprocess.STDOUT)


def run(
    command: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None
) -> None:
    print("+", subprocess.list2cmdline(command))
    subprocess.run(command, cwd=cwd, check=True, env=env)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def copy_checked(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    if source.read_bytes() != destination.read_bytes():
        raise SystemExit(f"copied file differs: {source} -> {destination}")


def validate_elf(readobj: Path, artifact: Path) -> str:
    report = checked_output(
        [str(readobj), "--file-headers", "--sections", "--program-headers", str(artifact)]
    )
    lower = report.lower()
    if "format: elf64" not in lower or "entry:" not in lower:
        raise SystemExit(f"{artifact} is not a valid ELF64 executable")
    return report


def target_flags(target_name: str) -> list[str]:
    if target_name == "x86_64":
        return ["-mno-mmx", "-mno-sse", "-mno-sse2", "-mno-avx", "-mno-avx2"]
    if target_name == "aarch64":
        return ["-mgeneral-regs-only"]
    raise SystemExit(f"unsupported Norx target: {target_name}")


def target_emulation(target_name: str) -> str:
    return {"x86_64": "elf_x86_64", "aarch64": "aarch64elf"}[target_name]


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
    target_dir.mkdir(parents=True, exist_ok=True)
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
    rust_candidates = [
        path
        for path in cargo_target_dir.rglob("norx-hello*")
        if path.is_file() and path.name in {"norx-hello", "norx-hello.exe"}
    ]
    if len(rust_candidates) != 1:
        raise SystemExit(f"expected one Rust ELF output, found: {rust_candidates}")
    copy_checked(rust_candidates[0], rust_elf)

    reports = {
        "c": validate_elf(readobj, c_elf),
        "rust": validate_elf(readobj, rust_elf),
    }
    for language, report in reports.items():
        (target_dir / f"hello-{language}.readobj.txt").write_text(report, encoding="utf-8")
        symbols = checked_output([str(objdump), "--syms", str(target_dir / f"hello-{language}.elf")])
        if "_start" not in symbols:
            raise SystemExit(f"{language} artifact has no debugger-visible _start symbol")
        (target_dir / f"hello-{language}.symbols.txt").write_text(symbols, encoding="utf-8")

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
    llvm_version = versions["llvm_version"]
    clang = tool_path("clang.exe" if os.name == "nt" else "clang", "NORX_CLANG")
    ld_lld = tool_path("ld.lld.exe" if os.name == "nt" else "ld.lld", "NORX_LD_LLD")
    readobj = tool_path(
        "llvm-readobj.exe" if os.name == "nt" else "llvm-readobj", "NORX_LLVM_READOBJ"
    )
    objdump = tool_path(
        "llvm-objdump.exe" if os.name == "nt" else "llvm-objdump", "NORX_LLVM_OBJDUMP"
    )
    for tool in (clang, ld_lld, readobj, objdump):
        version = checked_output([str(tool), "--version"])
        if llvm_version not in version:
            raise SystemExit(f"{tool} version is not pinned to LLVM {llvm_version}: {version}")

    rustc = rust_command(versions["rust_toolchain"])
    cargo = cargo_command(versions["rust_toolchain"])
    rust_version = checked_output([*rustc, "-Vv"])
    if versions["rustc_version"] not in rust_version or versions["rustc_commit"] not in rust_version:
        raise SystemExit(f"rustc does not match toolchain pin:\n{rust_version}")

    sysroot = TOOLCHAIN_ROOT / "sysroot"
    canonical_header = REPO_ROOT / "userspace" / "include" / "norx" / "syscall.h"
    canonical_stdint = REPO_ROOT / "userspace" / "include" / "stdint.h"
    copy_checked(canonical_header, sysroot / "include" / "norx" / "syscall.h")
    rootfs = Path(os.environ.get("NORX_ROOTFS", REPO_ROOT / "test-rootfs"))
    copy_checked(canonical_header, rootfs / "usr" / "include" / "norx" / "syscall.h")
    copy_checked(canonical_stdint, sysroot / "include" / "stdint.h")
    copy_checked(canonical_stdint, rootfs / "usr" / "include" / "stdint.h")

    args.out.mkdir(parents=True, exist_ok=True)
    results = {}
    for target_name, target_info in (
        ("x86_64", abi["targets"]["x86_64"]),
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
            output_root=args.out,
            sysroot=sysroot,
        )
        for language in ("c", "rust"):
            artifact = Path(results[target_name][language])
            copy_checked(
                artifact,
                rootfs / "tests" / "toolchain" / target_name / artifact.name,
            )

    manifest_dir = rootfs / "var" / "lib" / "toolchain"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_lines = [
        'schema = "toolchain-build"',
        "version = 1",
        f'llvm_version = "{llvm_version}"',
        f'rustc_version = "{versions["rustc_version"]}"',
        f'rustc_commit = "{versions["rustc_commit"]}"',
        f'abi_version = {abi["version"]}',
        "",
    ]
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
    manifest_path.write_text("\n".join(manifest_lines), encoding="utf-8")
    print(f"toolchain smoke build passed; manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
