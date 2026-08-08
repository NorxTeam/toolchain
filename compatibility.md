# Nordix SDK compatibility

The SDK release manifest is [`sdk.toml`](sdk.toml). A consumer must select an
exact target triple and verify the embedded `norx-userspace-abi` version before
using the headers, startup objects, archives, or linker files.

The first compatibility rules are intentionally strict:

- `abi_version`, syscall register conventions, object format, page size,
  `_start` startup layout, and target triple must match exactly;
- an SDK patch/release may fix build scripts, diagnostics, or implementation
  bugs while preserving those values;
- changing syscall numbers or registers, startup stack layout, C structure
  layout, relocation policy, floating-point policy, or target triple requires
  a new ABI version and a new consumer compatibility gate;
- static ELF is the only published link mode in SDK 0.1.0. Dynamic linking,
  pointer-based file I/O, and asynchronous signal delivery remain staged and
  must not be enabled by a consumer based only on this SDK;
- kernel and userspace repositories must fail closed when the requested SDK
  ABI or target triple is missing instead of silently selecting a nearby
  version.

`toolchain/scripts/publish-sdk.py` creates one deterministic archive per target
and an index with the archive hashes. The archive is a release staging format;
Gamma's future `.gpk` format owns installation, signatures, and system-profile
activation.
