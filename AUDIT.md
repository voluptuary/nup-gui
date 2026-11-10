# Adversarial audit — 2026-11-10

The audit found and fixed the 16 groups of issues below. It covered every tracked
Python module, both Windows build scripts, the devcontainer lifecycle, CI, and
packaging/documentation. This is a source review with bounded adversarial tests,
not a certification that every possible vulnerability has been found.

## Findings and fixes

Severity describes impact when the affected operation is used with malicious or
changing local input; it is not a claim of a remotely exploitable service.

| ID | Severity | Finding | Implemented fix and evidence |
| --- | --- | --- | --- |
| A01 | High | CLI tree extraction trusted node names, followed pre-existing destination links, and overwrote files. Flat rescue extraction also accepted path separators. GUI whole-dump extraction already had stronger checks. | Shared extraction preflight rejects traversal, aliases, case collisions, unsafe Windows names, links/junctions, and nonempty destinations. Files are created exclusively; flat extraction streams and verifies content. Existing files and outside-directory sentinels are protected. |
| A02 | High | Metadata editing used `input.nup.tmp`, overwriting an unrelated file or following a planted link. Error cleanup could unlink that pathname even when the editor had not created it. | Unique, exclusively created sibling temporary files; cleanup removes only the file created by the current edit. Original file permissions are preserved. |
| A03 | High | Reader validation omitted short-TOC handling, child-index bounds, cycles, overlapping child slots, inconsistent extent/metadata overlap, several reserved fields, and empty/multiple-base package cases. Malformed input could cause raw exceptions, nontermination in traversal, or inconsistent interpretation. | Checked arithmetic/bounds precede table traversal, iterative cycle detection covers orphan subgraphs, child ordering/uniqueness is checked, region overlaps allow only identical shared extents, and malformed structures produce `NupError`. Includes 400 deterministic, authenticated-TOC mutations. |
| A04 | High | `read_file()` skipped content hashes and performed a one-shot decompression whose allocation could follow a forged frame size. Deep verification buffered whole files and could leak mappings on malformed input. Short output writes were not handled. | Shared streaming read/size/hash checks; frame content size must match the file record, decoder windows are limited to 256 MiB, short writes are completed or rejected, and verification uses a discard sink and closes handles on every path. Corrupt compressed data becomes a controlled domain error. |
| A05 | High | Packing followed source file links, could block on special files, used a separate path size lookup, and could hash one version of a file but store another. Output creation followed a check-then-overwrite pattern. | Regular-file reads reject links/reparse points and special files, use descriptor sizes and no-follow/nonblocking flags where supported, and verify the bytes actually stored against the hashing pass. Outputs are created exclusively; incomplete outputs created by the packer are removed. Source depth is bounded at 256 levels. |
| A06 | High | Application metadata verification happened after replacing the target. Editing could also overwrite a package replaced by another editor during the operation. | Verify application metadata in the staged file before replacement. Detect changes to the opened file and newer destination identities; retries recheck the destination. A competing successful edit is preserved. Windows/Wine creation/change-time differences are handled without dropping inode, size or modification-time checks. |
| A07 | Medium | GUI transfers cleared fields missing from the source; incoming NACP/localized-only values could lose to stale defaults; publisher-only NACP entries could be missed. Choosing a target reset manual edits. Unchanged imported fields could be rewritten from their trimmed display values. | Preserve absent source values, materialize defaults only when needed to preserve effective values, read NACP title/publisher independently, retain manual edits on target selection, and preserve literal source TLV bytes unless explicitly edited. Full NACP/localized payloads remain intact. |
| A08 | Medium | Sidecar JSON accepted incomplete/wrongly typed identities and malformed shapes. A forged generated-artwork entry could suppress arbitrary content during repacking. | Validate the schema, numeric ranges/flags, canonical contained paths, duplicate paths, metadata framing, and artwork hashes/flags. Generated-artwork exclusions are restricted to conventional control icons under declared packages. Invalid manifests fail before output creation. |
| A09 | Medium | Metadata reserved fields and duplicate localized tags were accepted; editing silently discarded the opaque tail that SPEC section 5 permits after complete records. | Reject malformed record sizes/reserved fields and duplicate/invalid language tags; preserve unknown/duplicate records and opaque trailing bytes. Existing legacy shifted-type recognition remains. |
| A10 | Medium | Failed log writes could interrupt worker exception handling and leave the UI busy indefinitely. Thread-start failures were not recovered. Image previews accepted unrelated Pillow decoders and uncaught pixel-bomb exceptions. Very long preview text could hide action buttons. | Diagnostic failures cannot interrupt worker completion; dialogs report unavailable logs. Worker/start failures restore controls and progress. Preview decoding is JPEG/PNG-only with a 16-megapixel budget and caught image errors. Preview labels are bounded without truncating editable or stored values. Deferred, error-only logging is retained. |
| A11 | Medium | Explicit application metadata was ignored for standalone update packages. DLC-only extracted dumps could not be discovered for repacking. | Non-split standalone containers attach application metadata to their first package; discovery supports DLC-only bundles. Update/DLC identity flags and payloads remain unchanged; DLC-only round trips are tested. |
| A12 | Medium | CLI numeric package selectors were treated as kinds, and invalid names could silently select the first package. `edit()` returned stale metadata offsets/sizes. | Numeric selectors select the requested index; unknown/out-of-range selectors fail. The editor returns the actual updated package record. |
| A13 | Medium | The Wine builder reused a predictable shared `/tmp` directory and deleted build subdirectories without checking ownership. Native PowerShell continued after pip failures. | Per-user cache with ownership/write-permission checks, a marker, and symlink refusal before deletion. Unmarked nonempty directories are preserved. PowerShell checks each pip exit code before build cleanup. Guard tests preserve a sentinel in rejected directories. |
| A14 | Medium | The environment had outdated pip/setuptools; declared dependency floors permitted affected Pillow versions. The advertised Python minimum did not match typing/enum behavior, and patched Pillow 13 requires Python 3.11+. | Upgrade pip/setuptools before installing the project under the existing overall lifecycle timeout; require setuptools 84.1+, Pillow 13+, and PyInstaller 6.22.3+ for builds. Source installs now require Python 3.11+; enum/type usage works there. The Windows runtime stays Python 3.12.10. Resolved Python-package scans report no known advisories. |
| A15 | Medium | CI targeted the obsolete `meow` branch, skipped GUI tests on native Windows by requiring `DISPLAY`, and uploaded the EXE despite documenting a ZIP. Actions used mutable major-version tags and checkout persisted credentials. | CI tests `gui`, PRs into `gui`, and version tags; Windows GUI tests run without `DISPLAY`. Upload the ZIP. Pin official action release commits, use a contents-read token, and disable persisted checkout credentials. Fix the README release link. |
| A16 | Low | CLI version/name output could emit terminal control sequences from untrusted metadata or names. | Escape nonprintable characters in terminal-facing labels/version output without changing stored metadata. |

The regression tests are in
[the adversarial suite](tools/nup/tests/test_adversarial.py),
[metadata tests](tools/nup/tests/test_metadata.py), and
[GUI tests](tools/nup/tests/test_gui_metadata.py).

## Compatibility gate

There is no format revision, new TLV, new codec, or changed alignment. Package
identities/flags, opaque NPDM/NACP/build IDs, unknown metadata, and game bytes are
preserved. Native NUP names remain virtual UTF-8 labels: host Windows filename
restrictions apply to filesystem extraction, not to NUP creation or native reads.

The pre-audit reference is commit `12c6ba1d47c9e3759ffe3e61de25e77f1f59cd07`.
With the same Zstandard version, ordinary packing, ordinary metadata edits, and
native-label fixtures are **byte-for-byte identical** to that implementation.

Actual consumer source revisions tested:

- [BananaNative](https://git.eden-emu.dev/moceure/BananaNative/src/commit/7ea6a966e4be51d5e2ac0be08543ff44c036e447),
  commit `7ea6a966e4be51d5e2ac0be08543ff44c036e447`.
- [Fritchii](https://github.com/Frizti/Fritchii/tree/f66ea633db6058efe31a9611718019e5bd1667eb),
  commit `f66ea633db6058efe31a9611718019e5bd1667eb`.

Eight fixtures cover packing, editing, NACP/localized metadata transfer, metadata
before extents with an extended header, extraction/repacking, native filenames,
standalone updates, and standalone DLC. They include ExeFS, raw/compressed/empty
files, shared extents, base/update/add-on identities, artwork, and publisher/title
metadata.

- **Fritchii:** compile its unchanged `nup_container.cpp` and VFS implementation
  with small test-only host filesystem/logging/build adapters. Each fixture must
  parse, expose the expected metadata, verify every file hash, and read every
  member, both through its memory cache and its disk-spill path.
- **BananaNative native reader:** compile byte-identical copies of its actual
  `nup_image.h`/`romfs_image.h`, with its platform SHA-256 call adapted to OpenSSL.
  Compare every returned RomFS file hash with the source dump for 20 package
  selector/fixture combinations.
- **BananaNative Java reader:** compile the actual launcher reader and related
  classes with test-only Android build constants; validate all package trees,
  member hashes, and displayed metadata.
- **BananaNative preparation tools:** its existing 13 loader/tool tests run
  against this repository's producer, then again after metadata editing: 26
  passing tests. They exercise selectors, reads/seeks/mmap, descriptor-backed
  loading, NSO parsing, ExeFS/RomFS/DLC preparation, and folder-versus-NUP output
  equivalence. The upstream Android preparation test stubs the rewriter; this
  does **not** claim real game translation or execution was tested.

[Machine-readable results](audit/consumer-compatibility.json) record the pinned
revisions and outcomes. [The opt-in runner](tools/nup/check_consumers.py) is
reproducible with source checkouts supplied by the user; it does not fetch or
modify either consumer. See AGENTS.md for its prerequisites and invocation.

## Validation

- Linux Python 3.12/Xvfb: **73 tests passed**, including live GUI tests.
- Windows Python 3.12.10/Wine64: **73 discovered; 70 passed, 3 skipped**. The skips
  are a POSIX FIFO and two real symlink-creation tests that Wine cannot execute.
  All three run on Linux; Windows reparse attributes are tested separately.
- The supported source minimum, Python 3.11, passed 53 core/CLI tests. GUI
  integration uses the configured Linux display and Windows runtime.
- 400 deterministic authenticated-TOC mutations must either open cleanly or
  produce `NupError`, with no uncontrolled parser exception or leaked mapping.
- The actual Wine build and post-create lifecycle ran successfully. Build-cache
  guard checks reject unmarked contents and symlinks without deleting a sentinel.
- The rebuilt x64 executable opens, processes Windows messages, and closes cleanly.
  ZIP integrity and single-EXE contents are checked before release upload.
- [Resolved Windows Python package scan](audit/dependency-scan.json): ten
  third-party build/runtime packages, no known advisories reported by pip-audit
  on 2026-11-10. Initial findings were in old development pip/setuptools. A
  candidate Pillow 12.3 floor was rejected after its scan; released builds use
  Pillow 13. No claim is made that earlier shipped executables contained the
  development environment's pip/setuptools versions.
- Shell syntax, license synchronization, and `git diff --check` pass. The updated
  workflow supplies an additional native-Windows build/smoke/test gate on the PR.

## Limits and remaining risks

- No commercial game data, Android device/GPU, full Fritchii application build,
  game boot, or real game recompilation was available. Passing format/loader tests
  is evidence of compatibility, not a universal guarantee for every title.
- Direct `read_file()` intentionally returns a complete byte string. TOC/metadata
  memory and total extraction time/disk usage still scale with real input size;
  there is no global disk quota. The decoder/preview budgets do not make arbitrary
  huge valid archives cost-free. Stream files when a complete byte string is not
  required.
- File identity checks catch ordinary concurrent modifications/replacements;
  filesystem operations are not a sandbox against another local process actively
  replacing directory ancestors or racing every check. Inputs/destinations should
  not be concurrently rewritten by an untrusted process.
- CLI extraction may leave newly created partial output after an integrity error;
  it does not overwrite prior content. GUI whole-dump extraction stages output
  transactionally. Multi-output CLI split packing is not an all-or-nothing batch.
- Minimum dependency bounds are not a lockfile. Future resolutions can differ;
  repeat scans and consumer checks when dependencies or consumers change.
- pip-audit covers Python-package advisories, not the embedded CPython runtime,
  operating system, every vendored native library, or antivirus classification.
  The existing Windows Python 3.12.10/Wine build target is retained and UPX stays
  disabled.

Primary references used for platform/dependency details:
[Windows filename rules](https://learn.microsoft.com/en-us/windows/win32/fileio/naming-a-file),
[Zstandard decompression API](https://python-zstandard.readthedocs.io/en/latest/decompressor.html),
[Pillow security fixes](https://github.com/python-pillow/Pillow/blob/main/docs/releasenotes/13.0.0.rst).
