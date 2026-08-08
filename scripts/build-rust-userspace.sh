#!/usr/bin/env sh
set -eu
exec python3 "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)/build-rust-userspace.py" "$@"
