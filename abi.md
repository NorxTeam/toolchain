# Norx userspace target and ABI definition

Status: Roadmap 5.1.2. The canonical values are in [`abi.toml`](abi.toml).
This is the userspace ABI; the kernel build targets remain
`x86_64-unknown-none` and `aarch64-unknown-uefi` and must not be used for
userland binaries.

## Targets and object format

| Userspace target | Kernel target | ELF machine | C ABI | Baseline |
| --- | --- | --- | --- | --- |
| `x86_64-unknown-norx` | `x86_64-unknown-none` | `EM_X86_64` | System V AMD64 | x86-64 integer ISA |
| `aarch64-unknown-norx` | `aarch64-unknown-uefi` | `EM_AARCH64` | AAPCS64 | ARMv8-A integer ISA |

Both produce ELF64 little-endian objects with 4 KiB page alignment. The first
published binaries are statically linked `ET_EXEC` images. `ET_DYN`/PIE and
shared objects are reserved staged profiles; the relocation lists in
`abi.toml` are the allowed starting set, not permission to ship a dynamic
loader before its process and rollback contracts pass.

## Language calling conventions

The application ABI is the native C ABI for its target. Syscall register
placement is a separate kernel boundary and must not leak into ordinary C or
Rust function calls.

### x86_64 System V AMD64

- Integer and pointer arguments use `RDI, RSI, RDX, RCX, R8, R9`; integer and
  pointer results use `RAX`.
- `RSP` is 16-byte aligned at a call boundary. The 128-byte red zone is
  available to user code and is not used by the kernel entry path.
- `RBX, RBP, and R12-R15` are callee-saved. The first profile does not expose
  floating-point or vector arguments because process FPU ownership is not yet
  implemented.

### AArch64 AAPCS64

- The first eight integer and pointer arguments use `X0-X7`; results use
  `X0`. `X19-X28`, `X29` (frame pointer), and `X30` (link register) follow
  the AAPCS64 preservation rules.
- `SP` is always 16-byte aligned at a public call boundary. There is no red
  zone. `X18` is reserved as the platform register and is not allocatable by
  Norx code.
- Floating-point/SIMD arguments are excluded from the initial profile until
  the scheduler and user entry path save and restore that state.

## Syscall ABI v1

The published boundary is `NORX_ABI_VERSION == 1` in
`userspace/include/norx/syscall.h` and `src/syscall.rs`:

- every call has a 64-bit number, six 64-bit logical argument words, and a
  64-bit result;
- x86_64 uses `RAX` for the number/result and
  `RDI, RSI, RDX, R10, R8, R9` for arguments through the `syscall` instruction;
- AArch64 uses `X8` for the number and `X0-X5` for arguments/result through
  `SVC #0`;
- success returns a non-negative word; failure returns the unsigned
  two's-complement representation of `-errno` (currently errors are bounded
  to the Linux-compatible range below 4096);
- `read` and `write` are reserved entries and return `-ENOSYS` until real
  process-owned user buffers and pinning are available. They must not fall
  back to host I/O.

`Args` is `#[repr(C)]`, 48 bytes, 8-byte aligned. `Timespec` is two signed
64-bit fields, 16 bytes, with no hidden padding contract beyond the C layout.
Unknown numbers, invalid descriptors, invalid child/wait state, and invalid
user ranges use the typed errno mapping documented in `syscall-abi.md`.

## Startup and termination

Every target uses a Norx-owned freestanding `_start`, never host `crt1` or a
host process startup object. The loader provides a 16-byte-aligned initial
stack containing:

```text
argc, argv[argc], NULL, envp[], NULL,
AT_PAGESZ, page_size, AT_ENTRY, entry, AT_NULL, 0
```

The startup object normalizes that stack into the language runtime, calls the
application entry point, and terminates through `norx_exit(status)`. The
current architecture register image is intentionally explicit: x86_64 reads
the stack at `RSP`; AArch64 enters with `X0=argc`, `X1=argv`, and `X2=envp`.
Panics and uncaught failures abort; no host exit, signal, or console fallback
is allowed.

## Linker and relocation contract

Userland gets architecture-local scripts
`linker/x86_64-norx.ld` and `linker/aarch64-norx.ld` assembled by the
toolchain project. They are separate from the kernel's
`norx-kernel/linker/x86_64.ld`. The first scripts must:

- emit `.text`, `.rodata`, `.data`, `.bss`, `.tdata`, and `.tbss` in that
  order with page-aligned load segments;
- keep code non-writable and data non-executable; reject W+X PT_LOAD output;
- retain the entry symbol `_start` and discard host comments/unwind metadata
  unless the selected runtime explicitly owns it;
- use a fixed static image base for `ET_EXEC`; PIE load bias must be a 4 KiB
  multiple and remain below the architecture's `USER_LIMIT`.

The static relocation sets are intentionally small and architecture-specific:
x86_64 starts with absolute and PC-relative 64-bit/32-bit relocations plus
`PLT32`; AArch64 starts with page-relative `ADR_PREL_PG_HI21`, low-12-bit add,
absolute-64, call, and jump relocations. `RELATIVE`, `GLOB_DAT`, `JUMP_SLOT`,
and the listed TLS relocations are staged dynamic-linker work.

## TLS, atomics, and floating point

- TLS uses static TLS first: x86_64 uses the `FS` base and AArch64 uses
  `TPIDR_EL0`. Dynamic TLS relocation forms are reserved, and thread creation
  cannot claim a complete TLS ABI before process context ownership exists.
- Integer atomics are required up to 64 bits. x86_64 uses locked integer
  operations; AArch64 uses ARMv8 LL/SC. 128-bit atomics, lock-free guarantees
  beyond that set, and device memory atomics are not part of v1.
- The initial userland profile has no compiler-generated MMX/SSE/AVX or
  FP/NEON state. C builds use the target's general-register-only profile and
  Rust builds disable the corresponding target features. A later hard-float
  profile must first define lazy FPU ownership, signal/register save rules,
  and a new compatibility gate.

## Compatibility and validation

The definition is intentionally narrower than Linux: no glibc, musl, POSIX,
WASI, C++ exceptions, or host-path compatibility is implied. A target or
runtime change must update `abi.toml`, the public C header, the Rust syscall
contract, and the corresponding negative/boot smoke before changing
`ABI_VERSION` or marking the toolchain gate complete.

The current kernel self-checks verify the syscall register boundary, pointer
validation, ELF stack layout, W+X rejection, and both architecture entry
wrappers. The next toolchain task must add the actual target specs and linker
scripts, then compile a freestanding object for each target and compare its
ELF headers against this definition.
