#!/usr/bin/env python3
"""Create deterministic, target-specific Nordix SDK/sysroot staging archives."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tarfile
from io import BytesIO
import sys
import tomllib


SCRIPT_ROOT = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_ROOT.parent.parent
TOOLCHAIN_ROOT = REPO_ROOT / "toolchain"
ROOTFS = Path(os.environ.get("NORDIX_ROOTFS", REPO_ROOT / "norx-rootfs"))
SDK_CONFIG = TOOLCHAIN_ROOT / "sdk.toml"
OUTPUT_ROOT = ROOTFS / "packages" / "sdk"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_toml(path: Path) -> dict:
    with path.open("rb") as stream:
        return tomllib.load(stream)


def files_under(source: Path, prefix: str) -> list[tuple[Path, str]]:
    if not source.is_dir():
        raise SystemExit(f"missing SDK source directory: {source}")
    return [
        (path, f"{prefix}/{path.relative_to(source).as_posix()}")
        for path in sorted((entry for entry in source.rglob("*") if entry.is_file()), key=lambda item: item.as_posix())
    ]


def one_file(source: Path, destination: str) -> tuple[Path, str]:
    if not source.is_file():
        raise SystemExit(f"missing SDK source file: {source}")
    return source, destination


def toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=True)


def manifest_text(config: dict, target_name: str, triple: str, entries: list[dict]) -> str:
    lines = [
        'schema = "nordix-sdk-manifest"',
        "version = 1",
        f"sdk_version = {toml_string(config['sdk_version'])}",
        f"release = {config['release']}",
        f"target = {toml_string(target_name)}",
        f"triple = {toml_string(triple)}",
        f"abi_schema = {toml_string(config['abi_schema'])}",
        f"abi_version = {config['abi_version']}",
        f"layout = {toml_string(config['layout'])}",
        "",
        "[compatibility]",
    ]
    for key, value in sorted(config["compatibility"].items()):
        if isinstance(value, str):
            rendered = toml_string(value)
        elif isinstance(value, bool):
            rendered = str(value).lower()
        else:
            rendered = str(value)
        lines.append(f"{key} = {rendered}")
    for entry in entries:
        lines.extend(
            [
                "",
                "[[files]]",
                f"path = {toml_string(entry['path'])}",
                f"size = {entry['size']}",
                f"sha256 = {toml_string(entry['sha256'])}",
            ]
        )
    return "\n".join(lines) + "\n"


def add_bytes(archive: tarfile.TarFile, name: str, data: bytes, epoch: int) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mode = 0o644
    info.mtime = epoch
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    archive.addfile(info, BytesIO(data))


def publish_target(config: dict, target_name: str, abi: dict) -> dict:
    target_info = abi["targets"][target_name]
    triple = target_info["triple"]
    source_files: list[tuple[Path, str]] = []
    source_files.extend(files_under(TOOLCHAIN_ROOT / "sysroot" / "include", "sysroot/include"))
    source_files.extend(files_under(ROOTFS / "usr" / "lib" / triple, f"sysroot/lib/{triple}"))
    source_files.extend(files_under(ROOTFS / "tests" / "runtime" / triple, f"tests/runtime/{triple}"))
    source_files.extend(
        [
            one_file(
                TOOLCHAIN_ROOT / "targets" / f"{target_name}-unknown-norx.json",
                f"sysroot/targets/{target_name}-unknown-norx.json",
            ),
            one_file(TOOLCHAIN_ROOT / target_info["linker_script"], f"sysroot/{target_info['linker_script']}"),
            one_file(TOOLCHAIN_ROOT / "abi.toml", "sysroot/abi.toml"),
            one_file(TOOLCHAIN_ROOT / "versions.toml", "sysroot/versions.toml"),
        ]
    )

    entries = [
        {"path": destination, "size": source.stat().st_size, "sha256": sha256_file(source)}
        for source, destination in sorted(source_files, key=lambda item: item[1])
    ]
    manifest = manifest_text(config, target_name, triple, entries)
    artifact_name = f"nordix-sdk-{config['sdk_version']}-r{config['release']}-{target_name}.tar"
    artifact = OUTPUT_ROOT / artifact_name
    artifact.parent.mkdir(parents=True, exist_ok=True)
    epoch = int(config.get("source_date_epoch", 0))
    with tarfile.open(artifact, mode="w", format=tarfile.PAX_FORMAT) as archive:
        add_bytes(archive, "manifest.toml", manifest.encode("utf-8"), epoch)
        for source, destination in sorted(source_files, key=lambda item: item[1]):
            add_bytes(archive, destination, source.read_bytes(), epoch)

    return {
        "name": artifact.name,
        "target": target_name,
        "triple": triple,
        "sha256": sha256_file(artifact),
        "size": artifact.stat().st_size,
    }


def main() -> int:
    config = read_toml(SDK_CONFIG)
    abi = read_toml(TOOLCHAIN_ROOT / "abi.toml")
    artifacts = [publish_target(config, target, abi) for target in config["targets"]]
    index_lines = [
        'schema = "nordix-sdk-index"',
        "version = 1",
        f"sdk_version = {toml_string(config['sdk_version'])}",
        f"release = {config['release']}",
        f"abi_version = {config['abi_version']}",
    ]
    for artifact in artifacts:
        index_lines.extend(
            [
                "",
                "[[artifacts]]",
                f"name = {toml_string(artifact['name'])}",
                f"target = {toml_string(artifact['target'])}",
                f"triple = {toml_string(artifact['triple'])}",
                f"size = {artifact['size']}",
                f"sha256 = {toml_string(artifact['sha256'])}",
            ]
        )
    index = OUTPUT_ROOT / "index.toml"
    index.write_text("\n".join(index_lines) + "\n", encoding="utf-8")
    print(f"SDK publish passed; index: {index}")
    for artifact in artifacts:
        print(f"{artifact['target']} {artifact['name']} sha256={artifact['sha256']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
