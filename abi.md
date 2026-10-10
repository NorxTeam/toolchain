# Native ARM64 ABI scope

The published native target is `aarch64-unknown-norx`, using AAPCS64 and
`EM_AARCH64` static ELF64 little-endian executables. The kernel boot target is
`aarch64-unknown-uefi`; UEFI is a boot artifact format, not a userspace ABI.
Native x86 SDK output is retired. WLI owns foreign ELF/PE architecture
classification and translation independently from this native ABI.

The executable ABI and limits are authoritative in `abi.toml`. The versioned
syscall structures and numbers come from `../userspace/include/norx/syscall.h`
and the generated Rust wrappers; `../userspace/abi/norx-abi.toml` records the
shared contract. AArch64 passes the syscall number in `x8`, arguments in
`x0` through `x5`, and the result in `x0`; errors are negative errno values.

## Native startup and ownership

The entry symbol is `_start`. Startup uses the versioned bounded block v1
validated by the Norx C/Rust runtime: magic/version/header size, at most 4096
bytes, 16 arguments and 16 environment entries, checked offsets, bounded
terminated strings, and `AT_PAGESZ`/`AT_ENTRY`/`AT_NULL`. It is not an arbitrary
unbounded POSIX initial stack. Kernel-owned mapped memory remains required;
validation of a header does not establish pointer accessibility by itself.

Descriptors belong to the process and are revoked on close or process exit.
Raw internal VFS/DMA handles do not cross the syscall boundary. ABI versions,
structure sizes, and reserved-zero fields are checked before consuming input.

## Compiler and linker constraints

`targets/aarch64-unknown-norx.json` selects the freestanding target and
`linker/aarch64-norx.ld` lays out separate executable and writable segments.
Use 16-byte stack alignment, reserve `x18`, and disable floating point until
FPU context switching is implemented. Integer atomics use the ARMv8 baseline.
TLS and dynamic linking remain staged and require their own runtime evidence.

Build tools must match reviewed exact realpaths/digests and version pins.
The ELF validator checks machine, ABI, entry, load segments, bounds, W^X,
interpreter absence, and dynamic segments before publishing output atomically
into a confined sysroot/rootfs. Reproducible host checks are evidence about
those build boundaries; target execution and security release gates remain
separate.
