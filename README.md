# Norx toolchain and SDK assembly

## Native target policy

Native builds, SDK publication, and package recipes support ARM64 only
(`aarch64-unknown-norx`, kernel `aarch64-unknown-uefi`). Native x86 target specs
and linker output have been retired. Historical register metadata and upstream
sources remain available for review; foreign x86 applications belong to WLI
and do not make x86 a native Norx platform.

This repository owns how Norx userspace is built and released. It is a small,
reproducible configuration and SDK assembly project, not a fork of a compiler.
Userspace source code lives in [`../userspace/`](../userspace/); this repository
must not grow a second copy of its headers or runtime sources.

The staging package recipe is [`gamma.toml`](gamma.toml). It contains no host
paths and records the target-aware command that assembles the reproducible
sysroot and fixture outputs.

## Repository layout

- `targets/` — Norx target specifications consumed by Rust and LLVM tools.
- `linker/` — architecture-specific linker scripts.
- `scripts/` — version checks, header staging, runtime builds, fixture builds,
  and SDK publication.
- `fixtures/` — toolchain-only C/Rust compiler and linker smoke sources.
- `abi.toml`, `abi.md`, `versions.toml`, `sdk.toml` — target contract, pinned
  host-tool versions, and SDK release metadata.
- `build/` — ignored generated output, including `build/sysroot/`; it is
  recreated from `userspace/` and never committed.

The ownership rule is simple: `userspace/` answers “what is linked into a
program?”, while `toolchain/` answers “how is that program built for Norx?”.

## Decision

Use upstream LLVM/Clang/lld and upstream Rust nightly as the initial compiler
base. Keep target descriptions, linker scripts, version pins, and build
manifests under this project; keep startup objects, headers, runtimes, and the
Rust userspace API in `../userspace/`.
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
| C startup and termination | `../userspace/runtime` | `_start`, syscall entry glue, `exit`, stack alignment, and early relocation setup | Local source; never borrow host `crt1`/`crti`/`crtn` |
| C headers and syscall wrappers | `../userspace/include` and `../userspace/runtime/include` | Versioned `norx/syscall.h` and freestanding type definitions | Local source; the generated sysroot is only a build copy |
| libc/libm and allocator | Norx-owned later | Small supported subset only after process, VFS, memory, and syscall contracts | Do not import host libc; use a maintained upstream base only after scope is explicit |
| C++ ABI and runtime | Deferred | A separately scoped `libsupc++`/exception policy if C++ is admitted | No exceptions/unwind by default; no host `libstdc++` leakage |
| Rust `core`/`alloc` userspace layer | Upstream crates plus `../userspace/rust` | Panic handler, allocator boundary, syscall wrappers, and feature gates | No `std` until the userspace ABI and filesystem/process lifecycle pass smoke |
| Debugger support | Upstream GDB/LLDB where usable | Target description, symbols, and QEMU launch recipes | No debugger fork; target scripts remain data/configuration |
| Build orchestration | Norx-owned scripts and CI | Version checks, isolated host/target paths, sysroot assembly, and artifact manifest | Scripts may fail closed on mixed host/target inputs |

“Norx-owned” means the source is part of the target contract and must be
versioned with the userspace project. It does not mean that a full runtime is
implemented by this decision.

## Boundary rules

1. Host tools run on the host; target headers and runtime sources come from
   `../userspace/`, while target specs and linker scripts come from this
   repository. The generated combination is `build/sysroot/`.
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
and Rust nightly against [`versions.toml`](versions.toml), after resolving
every executable through the reviewed host-specific
[`toolchain-pins.toml`](toolchain-pins.toml.example) policy. Each tool is
matched by exact realpath and SHA-256 before and during use; `NORX_*` and
`RUSTC` may only select that already-pinned file. It builds freestanding C and
Rust fixtures for the native ARM64 target spec, links them with the architecture
linker scripts, parses their ELF bytes directly for the target machine, ABI,
segments, entry, W^X, and absent interpreter/dynamic linker, and copies the
tested binaries plus a hash manifest atomically into
[`../test-rootfs`](../test-rootfs). Cargo uses the installed pinned `rust-src`
with `build-std=core` and `--offline`; no host libc or host headers enter the
sysroot.

Before a build, provision `toolchain-pins.toml` from the intended compiler
installation and review both fields for every tool listed in the example. The
file is host-specific and ignored by Git; a missing or malformed file fails
closed instead of falling back to `PATH`. `NORX_ROOTFS` and `--out` are also
confined to `test-rootfs` and `toolchain/build` respectively, and an existing symlink in any
published path is rejected.

Run it with `python toolchain/scripts/build.py` from the repository root, or
use `scripts/build.ps1` / `scripts/build.sh`. Debugger-facing details and the
graphical QEMU GDB-stub recipes are in [`debugger.md`](debugger.md).

The Rust userspace gate is separate because `alloc` must link against the
target runtime archive. Run `python toolchain/scripts/build-rust-userspace.py`
after `build-runtime.py`; it builds `core`, `alloc`, and `compiler_builtins`
offline and stages the no-std userspace API fixture under the test rootfs.

The first quickinit bootstrap gate is also separate from the host policy tests.
Run `python toolchain/scripts/build-quickinit.py` after `build-runtime.py`; it
builds the freestanding quickinit contract ELF for native ARM64, validates its
`_start` symbol, and stages the artifact plus hashes under the test rootfs.
This bootstrap only proves the current write/getpid/wait/exit ABI slice; it is
not yet the full PID1 supervisor handoff.

## Versioned SDK/sysroot release

Roadmap 5.1.7 uses [`sdk.toml`](sdk.toml) and
[`compatibility.md`](compatibility.md) as the release contract. After the
toolchain, runtime, and Rust gates pass, run:

```sh
python toolchain/scripts/publish-sdk.py
```

The script creates deterministic target-specific archives and
`test-rootfs/packages/sdk/index.toml`. Each archive carries its own manifest,
target triple, ABI version, compatibility fields, headers, runtime archives,
linker/target files, and tested C/C++ fixtures. This is SDK release staging,
not Gamma installation or `.gpk` publication.

## Source-boundary CI guard

Run `python scripts/check_boundaries.py` after SDK publication (use
`--require-sdk` in a release job). The guard rejects tracked `build/` and
`sysroot/` paths, checks the staged `test-rootfs/usr/include` tree, and compares
every `sysroot/include/*` member in each published SDK archive with the
canonical headers under `../userspace/`. The stdlib-only regression checks run
with `python -m unittest discover -s tests -p 'test_*.py'`.

The complete cross-repository dependency graph and release hand-off is in
[`release-flow.md`](release-flow.md). It is the required reading before adding
another language runtime or changing the SDK contents.

External ports follow [`upstream-policy.md`](upstream-policy.md), including
the preserved remote/tag/license boundary and the reviewable Norx patch queue.
Start each maintained external fork from
[`UPSTREAM.md.template`](UPSTREAM.md.template); never invent provenance for a
repository that has not yet been forked.

## Build trust boundary checks

Run `python3 scripts/test_build.py` with Python 3.11 or newer. The negative
corpus covers tool realpath/digest mismatches, malformed ELF images, executable
permissions, interpreter rejection, symlink publication, and root confinement.
These host checks stage P1-15; target builds and QEMU remain release gates.
The pin manifest trusts an administrator-reviewed host installation. Host
processes able to modify pinned executables between verification and execution
remain outside this boundary.
