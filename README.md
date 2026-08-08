# Norx toolchain strategy

Status: decision for Roadmap 5.1.1. This project deliberately starts as a
small, reproducible configuration and sysroot project. It is not a fork of a
compiler and it does not claim that a userspace C library or `std` is ready.

The staging package recipe is [`gamma.toml`](gamma.toml). It contains no host
paths and records the target-aware command that assembles the reproducible
sysroot and fixture outputs.

## Decision

Use upstream LLVM/Clang/lld and upstream Rust nightly as the initial compiler
base. Keep Norx-specific behavior in target descriptions, linker scripts,
startup objects, headers, runtimes, and build manifests under this project.
Create a maintained compiler fork only if an upstream target or ABI defect is
demonstrated by a reduced test case and cannot be fixed through a target file,
linker option, runtime shim, or an accepted upstream change.

This gives C, C++, and Rust the same ELF64 little-endian object format and
architecture-local ABI while keeping host tools separate from the target
sysroot. It also lets the kernel and the first userland programs share the
already documented syscall ABI without copying host headers or libraries into
the image.

## Component ownership

| Component | Initial source | Norx-owned customization | Fork or patch policy |
| --- | --- | --- | --- |
| LLVM code generation and assembler | Upstream LLVM | Target feature selection and reproducible version pin | No fork; upstream bug report/reduced test first |
| Clang C/C++ driver | Upstream Clang | Norx target configuration, `--sysroot`, freestanding defaults | No driver fork for startup or include paths |
| lld linker | Upstream lld | Norx linker scripts and explicitly selected relocation options | No fork; keep linker scripts reviewable in this project |
| GNU binutils compatibility tools | Upstream, only where required by a build | Target-prefixed wrapper names and version checks | Optional; never make host binutils output part of the ABI |
| Rust compiler and LLVM backend | Upstream Rust nightly | Custom target specifications, linker integration, panic policy, and `core`/`alloc` build manifests | No rustc fork; upstream issue or local target spec first |
| `compiler_builtins` | Upstream crate | `no_std` feature selection and target build flags | No patch unless a reduced target failure is accepted upstream or isolated here |
| C startup and termination | Norx-owned freestanding objects | `_start`, syscall entry glue, `exit`, stack alignment, and early relocation setup | Local source; never borrow host `crt1`/`crti`/`crtn` |
| C headers and syscall wrappers | Norx-owned | Versioned `norx/syscall.h` and freestanding type definitions | Local source reviewed against `userspace/include/norx/syscall.h` |
| libc/libm and allocator | Norx-owned later | Small supported subset only after process, VFS, memory, and syscall contracts | Do not import host libc; use a maintained upstream base only after scope is explicit |
| C++ ABI and runtime | Deferred | A separately scoped `libsupc++`/exception policy if C++ is admitted | No exceptions/unwind by default; no host `libstdc++` leakage |
| Rust `core`/`alloc` userspace layer | Upstream crates plus Norx-owned API crate | Panic handler, allocator boundary, syscall wrappers, and feature gates | No `std` until the userspace ABI and filesystem/process lifecycle pass smoke |
| Debugger support | Upstream GDB/LLDB where usable | Target description, symbols, and QEMU launch recipes | No debugger fork; target scripts remain data/configuration |
| Build orchestration | Norx-owned scripts and CI | Version checks, isolated host/target paths, sysroot assembly, and artifact manifest | Scripts may fail closed on mixed host/target inputs |

“Norx-owned” means the source is part of the target contract and must be
versioned with the userspace project. It does not mean that a full runtime is
implemented by this decision.

## Boundary rules

1. Host tools run on the host; target headers, startup objects, libraries, and
   linker scripts come only from the Norx sysroot.
2. The first C and Rust user programs are freestanding and statically linked.
   Dynamic linking, TLS, unwinding, and `std` are separate gates.
3. The toolchain consumes the versioned syscall ABI from
   [`../userspace/include/norx/syscall.h`](../userspace/include/norx/syscall.h)
   and must not include kernel-private Rust modules.
4. Architecture differences stay in target files and startup/entry code. A
   shared header or Rust API may expose logical operations, but it may not
   hide register conventions, stack alignment, or pointer-width assumptions.
5. Every compiler or runtime patch must include: upstream status, a reduced
   test, the affected target(s), the removal condition, and a QEMU or host
   smoke assertion. A patch without those fields is rejected.

## What is intentionally not decided here

The next Roadmap item freezes the exact target triples, object flags, calling
convention, startup layout, relocation set, TLS model, stack alignment,
atomics, floating-point policy, and feature levels. This document chooses the
source strategy and ownership boundary only; it does not silently freeze those
ABI details early.

The first implementation also does not promise POSIX, glibc, `libstdc++`,
WASI, or a host-compatible package manager. Unsupported behavior must remain a
typed build error or an explicit runtime error until its ABI and failure path
are documented.

## Decision gate

Roadmap 5.1.1 is complete when this strategy remains the source of truth and
the following are true:

- no maintained compiler fork or unreviewed host-library copy is required;
- every local component has an owner and patch/removal policy in the table;
- the existing versioned syscall header is the only published kernel boundary;
- the next target/ABI document can be implemented without changing this
  source strategy.

The implementation gates that follow this decision must add reproducible
version pins and artifact hashes before publishing an SDK or sysroot.

## Reproducible smoke toolchain

Roadmap 5.1.3 is implemented by `scripts/build.py`. It checks LLVM/Clang/lld
and Rust nightly against [`versions.toml`](versions.toml), builds freestanding
C and Rust fixtures for both custom target specs, links them with the
architecture linker scripts, validates ELF64 headers and `_start` symbols,
and copies the tested binaries plus a hash manifest into
[`../norx-rootfs`](../norx-rootfs). Cargo uses the installed pinned `rust-src`
with `build-std=core` and `--offline`; no host libc or host headers enter the
sysroot.

Run it with `python toolchain/scripts/build.py` from the repository root, or
use `scripts/build.ps1` / `scripts/build.sh`. Debugger-facing details and the
graphical QEMU GDB-stub recipes are in [`debugger.md`](debugger.md).

The Rust userspace gate is separate because `alloc` must link against the
target runtime archive. Run `python toolchain/scripts/build-rust-userspace.py`
after `build-runtime.py`; it builds `core`, `alloc`, and `compiler_builtins`
offline and stages the no-std Nordix API fixture under the test rootfs.

## Versioned SDK/sysroot release

Roadmap 5.1.7 uses [`sdk.toml`](sdk.toml) and
[`compatibility.md`](compatibility.md) as the release contract. After the
toolchain, runtime, and Rust gates pass, run:

```sh
python toolchain/scripts/publish-sdk.py
```

The script creates deterministic target-specific archives and
`norx-rootfs/packages/sdk/index.toml`. Each archive carries its own manifest,
target triple, ABI version, compatibility fields, headers, runtime archives,
linker/target files, and tested C/C++ fixtures. This is SDK release staging,
not Gamma installation or `.gpk` publication.
