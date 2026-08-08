# Norx debugger support

The cross-toolchain smoke build keeps DWARF and the `_start` symbol in its C
and Rust fixtures. `llvm-readobj` validates ELF headers/program headers and
the pinned `llvm-objdump --syms` pass validates that the entry symbol remains
visible to a debugger. These checks run from `scripts/build.py` and their
reports stay beside each fixture under `toolchain/build/<arch>/`.

For a graphical local QEMU session, start the machine with the GDB stub and
the same display policy used by the integration tests:

```text
x86_64: qemu-system-x86_64 ... -display gtk -s -S
aarch64: qemu-system-aarch64 ... -display gtk -device ramfb -gdb tcp::1234 -S
```

Connect an architecture-capable GDB/LLDB to `localhost:1234`, load the
unstripped kernel or userspace ELF from the matching build directory, and set
a breakpoint on `_start`. The existing TDM GDB is a host Windows debugger;
it is not treated as an AArch64 target debugger. A target-aware GDB/LLDB is a
separate SDK packaging choice and must be pinned before it is shipped.

The current gate proves symbol and remote-stub compatibility. It does not
claim that userspace execution, process creation, or syscall stepping is
ready; those remain the later 5.1.6 and 5.2 Roadmap gates.
