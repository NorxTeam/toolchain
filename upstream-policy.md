# Upstream port policy

Status: Roadmap 5.1.8. This policy applies to every future Norx repository
that imports or adapts an external project. It does not retroactively turn the
current Norx-owned repositories into upstream forks: their remotes are owned
by `NorxTeam`, and `nsh` currently has no configured remote.

## Default decision

Every external project that enters the Norx source tree or is shipped as a
Norx package must start as a maintained Git fork of its upstream repository.
Keep the upstream project recognizable and updateable. Norx work belongs in a
small, reviewable patch queue; mature upstream code must not be rewritten from
scratch merely to fit the first package layout.

An unmodified upstream checkout may be used only as a transient host build
dependency when it is not copied into a Norx repository, is not presented as a
Norx package, and needs no Norx port. That is a host-tool input, not an
upstream-port exception. A package rename or release-tarball copy is never a
reason to skip the fork.

The pinned LLVM/Clang/lld and Rust inputs selected by Roadmap 5.1.1 remain
upstream host dependencies; they are deliberately not Norx forks because they
are not being shipped as Norx ports in this stage. Any future shipped or
ported external component follows the mandatory-fork rule above.

Reject a port when it requires silently removing license notices, bypassing a
security boundary, carrying an unreviewable generated vendor tree, or
pretending that unsupported host APIs work on Norx. Record the decision and
the reason in the component's provenance file before implementation starts.

## Repository shape

A maintained port must preserve these boundaries:

```text
upstream remote  ->  upstream/<tag-or-commit>  ->  norx/<target-branch>
                                             \->  patches/<ordered-series>
```

- Keep a remote named `upstream` pointing at the original project.
- Keep upstream tags and the imported upstream commit in history; do not
  replace them with a generated snapshot.
- Keep Norx changes on a branch or ordered patch series that can be rebased
  onto a later upstream revision.
- Keep the package recipe, target adapter, tests, and integration metadata in
  the Norx-owned layer unless the change is accepted upstream.
- Never commit build directories, downloaded archives, generated sysroots,
  or target binaries as a substitute for source provenance.

An upstream fork must retain the upstream `LICENSE`, `COPYING`, `NOTICE`,
copyright headers, and attribution files. If the project has a separate
trademark or branding policy, keep the upstream product name only where the
policy permits it and choose a distinct Norx package/product name when it does
not. A package cannot pass the port gate with an unresolved license or
trademark obligation.

## Required provenance record

Before a fork is built, add `UPSTREAM.md` (or an equivalent generated Gamma
provenance section) containing all fields below:

```text
project: <Norx package/repository name>
upstream_url: <canonical upstream Git URL>
norx_fork_url: <Norx fork URL, or "not published yet">
upstream_remote: upstream
baseline_tag: <exact tag, or "none">
baseline_commit: <full immutable commit ID>
imported_at: <UTC date>
license_spdx: <SPDX expression>
license_files: <LICENSE/COPYING/NOTICE paths retained in the fork>
trademark_obligations: <summary and review reference, or "none found">
patch_series: <ordered patch directory/file list>
build_profile: <Gamma recipe/profile name and relevant flags>
supported_targets: <exact Norx target triples>
generated_artifacts: <manifest path, hash algorithm, and release scope>
last_sync: <UTC date and resulting commit>
```

The baseline must be a full commit ID even when a human-facing tag is also
recorded. Artifact hashes describe outputs, not source identity; the source
identity remains the upstream commit plus the ordered Norx patches.

## Patch and review rules

Each downstream patch has one purpose and a stable order. Prefer patches that
can be upstreamed, in this order:

1. portable bug or security fix with a reduced test;
2. build-system or target integration change;
3. Norx ABI adapter and capability boundary;
4. packaging, diagnostics, and release metadata.

Do not mix a formatting sweep, generated files, license changes, and a target
port in one patch. Every patch must state its affected targets, test command,
upstream status (`submitted`, `accepted`, `rejected`, or `Norx-only`), and
removal condition. A Norx-only workaround must have a bounded reason and an
issue or upstream discussion reference when one exists.

The review gate rejects:

- a fork without a preserved upstream remote and immutable baseline;
- a patch queue that cannot be applied or rebased in a clean checkout;
- missing or changed upstream license/notice files without legal review;
- build flags that fetch the host libc, host paths, or network content during a
  reproducible build;
- generated artifacts without a reproducible command and hash manifest;
- a package recipe that hides the upstream identity or the Norx patch set.

## Build and release obligations

The Gamma recipe is the executable build contract. It must record the source
coordinate, target triples, offline/network policy, build profile, declared
outputs, runtime dependencies, and the provenance record path. The build must
produce a manifest containing at least:

- upstream baseline commit and local patch-set revision;
- exact build options and target triples;
- license/provenance file hashes;
- generated artifact paths, sizes, and SHA-256 values;
- host-tool and SDK/ABI versions used for the build.

The release archive must include the retained upstream notices and the
provenance metadata when the upstream license requires redistribution. A
generated SDK or rootfs is never the only copy of that information.

## Gamma recipe and lock metadata

For the first real external fork, the package recipe must carry the immutable
source identity instead of leaving it only in prose:

```toml
[source]
kind = "git-fork"
repository = "https://github.com/NorxTeam/<fork>.git"
upstream_repository = "https://github.com/<upstream>/<project>.git"
upstream_tag = "<tag-or-none>"
upstream_commit = "<full-commit>"
patch_series = "patches/series"

[provenance]
document = "UPSTREAM.md"
license_spdx = "<SPDX expression>"
trademark_review = "<review reference or none>"
build_options = ["<exact option>"]
generated_manifest = "<path to hash manifest>"
```

The corresponding lock entry freezes the source and generated evidence used
for a release:

```toml
[packages.<name>.source]
repository = "https://github.com/NorxTeam/<fork>.git"
upstream_repository = "https://github.com/<upstream>/<project>.git"
upstream_commit = "<full-commit>"
patch_series_sha256 = "<hash of ordered series>"

[packages.<name>.provenance]
document_sha256 = "<UPSTREAM.md hash>"
license_files_sha256 = "<notice/license manifest hash>"
build_options_sha256 = "<normalized options hash>"
artifact_manifest = "<manifest path>"
artifact_manifest_sha256 = "<manifest hash>"
```

The recipe identifies what to build; the lock identifies the exact upstream
commit, patch series, provenance record, options, and generated artifact
manifest that were accepted. Norx-owned recipes such as the current
`toolchain` and `userspace` packages must not receive empty or invented
upstream fields. Add these tables with real values when the first external
fork is introduced.

## Sync policy

Upstream synchronization is a controlled update, not an ad-hoc merge:

1. fetch the configured `upstream` remote and select a new immutable tag or
   commit;
2. create a sync branch from that upstream revision;
3. apply or rebase the ordered Norx patch series;
4. resolve conflicts while preserving upstream notices and reviewing security
   changes;
5. regenerate the provenance record and patch status;
6. run host tests, target builds, malformed-input/security tests, and QEMU
   smoke tests for every supported target;
7. publish the new artifact/hash manifest only after the old revision remains
   available for rollback.

The future per-fork CI job must perform these same steps in a clean checkout,
fail on conflicts or missing provenance, and report the last known-good
upstream commit. Until a component has an actual upstream fork, its CI must
not fabricate an upstream baseline; the policy check should report the
component as `Norx-owned` or `unmanaged`, not as synced.
