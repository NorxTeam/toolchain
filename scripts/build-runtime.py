#!/usr/bin/env python3
"""Build the target-owned Norx C/C++ runtime subset and link fixtures."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib

SCRIPT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_ROOT))
from build import (  # noqa: E402
    REPO_ROOT,
    TOOLCHAIN_ROOT,
    checked_output,
    copy_checked,
    load_toml,
    run,
    target_emulation,
    target_flags,
    tool_path,
    validate_elf,
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stage_headers(root: Path, sysroot: Path, rootfs: Path) -> None:
    sources = [REPO_ROOT / "userspace" / "include", REPO_ROOT / "userspace" / "runtime" / "include"]
    for source_root in sources:
        for source in source_root.rglob("*"):
            if not source.is_file():
                continue
            relative = source.relative_to(source_root)
            copy_checked(source, sysroot / "include" / relative)
            copy_checked(source, rootfs / "usr" / "include" / relative)


def compile_common(target_info: dict, target_name: str, sysroot: Path) -> list[str]:
    return [
        f"--target={target_info['triple']}",
        "-ffreestanding",
        "-fno-builtin",
        "-fno-stack-protector",
        "-fno-unwind-tables",
        "-fno-asynchronous-unwind-tables",
        "-nostdinc",
        "-isystem",
        str(sysroot / "include"),
        *target_flags(target_name),
    ]


def compile_source(command: list[str], source: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    run([*command, "-c", str(source), "-o", str(output)])


def archive(ar: Path, output: Path, objects: list[Path]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    run([str(ar), "rcs", str(output), *(str(object_file) for object_file in objects)])


def link_fixture(
    *,
    ld_lld: Path,
    target_name: str,
    linker_script: Path,
    output: Path,
    objects: list[Path],
    libraries: list[Path],
    undefined: str | None = None,
) -> None:
    command = [
        str(ld_lld),
        "-m",
        target_emulation(target_name),
        "-T",
        str(linker_script),
        "--no-dynamic-linker",
        "-z",
        "max-page-size=0x1000",
    ]
    if undefined:
        command.extend(["--undefined", undefined])
    command.extend(["-o", str(output), *(str(object_file) for object_file in objects)])
    command.extend(str(library) for library in libraries)
    run(command)


def reject_libm(clang: Path, target_info: dict, target_name: str, sysroot: Path, output: Path) -> None:
    command = [
        str(clang),
        *compile_common(target_info, target_name, sysroot),
        "-fsyntax-only",
        str(REPO_ROOT / "userspace" / "examples" / "libm_reject.c"),
    ]
    completed = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if completed.returncode == 0 or "libm is unavailable" not in completed.stderr:
        raise SystemExit("math.h did not fail closed with the expected Norx libm diagnostic")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(completed.stderr, encoding="utf-8")


def main() -> int:
    versions = load_toml(TOOLCHAIN_ROOT / "versions.toml")
    abi = load_toml(TOOLCHAIN_ROOT / "abi.toml")
    llvm_version = versions["llvm_version"]
    clang = tool_path("clang.exe" if os.name == "nt" else "clang", "NORX_CLANG")
    clangxx = tool_path("clang++.exe" if os.name == "nt" else "clang++", "NORX_CLANGXX")
    ld_lld = tool_path("ld.lld.exe" if os.name == "nt" else "ld.lld", "NORX_LD_LLD")
    ar = tool_path("llvm-ar.exe" if os.name == "nt" else "llvm-ar", "NORX_LLVM_AR")
    readobj = tool_path(
        "llvm-readobj.exe" if os.name == "nt" else "llvm-readobj", "NORX_LLVM_READOBJ"
    )
    for tool in (clang, clangxx, ld_lld, ar, readobj):
        if llvm_version not in checked_output([str(tool), "--version"]):
            raise SystemExit(f"{tool} is not pinned to LLVM {llvm_version}")

    sysroot = TOOLCHAIN_ROOT / "sysroot"
    rootfs = Path(os.environ.get("NORX_ROOTFS", REPO_ROOT / "test-rootfs"))
    stage_headers(REPO_ROOT, sysroot, rootfs)
    build_root = TOOLCHAIN_ROOT / "build" / "runtime"
    results: dict[str, dict[str, str]] = {}

    c_sources = [
        REPO_ROOT / "userspace" / "runtime" / "src" / "libc" / "string.c",
        REPO_ROOT / "userspace" / "runtime" / "src" / "libc" / "unistd.c",
        REPO_ROOT / "userspace" / "runtime" / "src" / "libc" / "stdlib.c",
        REPO_ROOT / "userspace" / "runtime" / "src" / "libc" / "threads.c",
        REPO_ROOT / "userspace" / "runtime" / "src" / "startup" / "start.c",
    ]
    for target_name, target_info in (
        ("x86_64", abi["targets"]["x86_64"]),
        ("aarch64", abi["targets"]["aarch64"]),
    ):
        target_dir = build_root / target_name
        common = compile_common(target_info, target_name, sysroot)
        c_objects: list[Path] = []
        for source in c_sources:
            object_file = target_dir / "obj" / f"{source.stem}.o"
            compile_source([str(clang), *common, "-g"], source, object_file)
            c_objects.append(object_file)

        startup_source = REPO_ROOT / "userspace" / "runtime" / "src" / "startup" / f"{target_name}.S"
        startup_object = target_dir / "obj" / "crt0.o"
        compile_source([str(clang), *common, "-g"], startup_source, startup_object)
        c_objects.append(startup_object)
        libc_archive = target_dir / "libnorxrt.a"
        archive(ar, libc_archive, c_objects)

        cxx_source = REPO_ROOT / "userspace" / "runtime" / "src" / "cxx" / "cxxabi.cpp"
        cxx_object = target_dir / "obj" / "cxxabi.o"
        compile_source(
            [
                str(clangxx),
                *common,
                "-nostdinc++",
                "-std=c++17",
                "-fno-exceptions",
                "-fno-rtti",
                "-fno-threadsafe-statics",
                "-g",
            ],
            cxx_source,
            cxx_object,
        )
        cxx_archive = target_dir / "libnorxcxx.a"
        archive(ar, cxx_archive, [cxx_object])

        c_smoke_object = target_dir / "obj" / "runtime_smoke.o"
        compile_source(
            [str(clang), *common, "-std=c11", "-g"],
            REPO_ROOT / "userspace" / "examples" / "runtime_smoke.c",
            c_smoke_object,
        )
        c_smoke = target_dir / "runtime-c.elf"
        link_fixture(
            ld_lld=ld_lld,
            target_name=target_name,
            linker_script=TOOLCHAIN_ROOT / target_info["linker_script"],
            output=c_smoke,
            objects=[startup_object, c_smoke_object],
            libraries=[libc_archive],
        )

        cxx_smoke_object = target_dir / "obj" / "cxx_smoke.o"
        compile_source(
            [str(clangxx), *common, "-std=c++17", "-fno-exceptions", "-fno-rtti", "-g"],
            REPO_ROOT / "userspace" / "examples" / "cxx_smoke.cpp",
            cxx_smoke_object,
        )
        cxx_smoke = target_dir / "runtime-cxx.elf"
        link_fixture(
            ld_lld=ld_lld,
            target_name=target_name,
            linker_script=TOOLCHAIN_ROOT / target_info["linker_script"],
            output=cxx_smoke,
            objects=[startup_object, cxx_smoke_object],
            libraries=[libc_archive, cxx_archive],
            undefined="__cxa_pure_virtual",
        )

        reject_libm(
            clang,
            target_info,
            target_name,
            sysroot,
            target_dir / "libm-reject.stderr.txt",
        )
        for artifact in (libc_archive, cxx_archive, c_smoke, cxx_smoke):
            validate_elf(readobj, artifact) if artifact.suffix == ".elf" else None
        results[target_name] = {
            "libc_sha256": sha256(libc_archive),
            "cxx_sha256": sha256(cxx_archive),
            "c_sha256": sha256(c_smoke),
            "cxx_smoke_sha256": sha256(cxx_smoke),
        }
        for artifact in (libc_archive, cxx_archive, c_smoke, cxx_smoke):
            destination = rootfs / ("tests/runtime" if artifact.suffix == ".elf" else "usr/lib") / target_info["triple"] / artifact.name
            copy_checked(artifact, destination)

    manifest_dir = rootfs / "var" / "lib" / "runtime"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        'schema = "runtime-build"',
        "version = 1",
        f'llvm_version = "{llvm_version}"',
        'exceptions = "disabled"',
        'rtti = "disabled"',
        'allocator = "unavailable_returns_enomem"',
        'libm = "deferred_no_fp_abi"',
        "",
    ]
    for target_name, target_results in results.items():
        lines.extend([f"[targets.{target_name}]", *[f'{key} = "{value}"' for key, value in target_results.items()], ""])
    (manifest_dir / "manifest.toml").write_text("\n".join(lines), encoding="utf-8")
    print(f"runtime build passed; manifest: {manifest_dir / 'manifest.toml'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
