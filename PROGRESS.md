# Progress & Change Log

This document records meaningful changes and enhancements made to `nup-gui` and its tooling.

## 0.3.1 GUI test build (2026-11-10)

- Moved existing metadata editing to the third radio option in the main window,
  retaining editor state when switching modes. Made editor buttons uniform and
  placed Transfer metadata on the right. Corrected a Windows-theme width mismatch
  found by the new GUI layout test.
- Added target-transfer confirmation with source/target paths, changed text/icon
  fields, localized/NACP changes, and preservation context. Cancelling leaves
  both source and target bytes unchanged; source-update confirmation remains.
- Added append-only UTF-8 error.log diagnostics for import/read failures, worker
  errors, validation errors, and unhandled Tk callbacks, including tracebacks.
  Dialogs show the log location; unwritable application directories fall back
  to user storage. Logs are ignored by Git.
- Verified metadata with :, &, $, accented text and Japanese through imports,
  reads, transfers, source updates, and dump round trips. Tested supported
  filenames with &, $, and Unicode; these tests found no character-escaping bug.
  Existing reported errors still need a real error.log to identify their cause.
- Retained --noupx in both build scripts. Enabled level-9 internal archive
  compression and excluded unused Pillow AVIF/WebP plugins and native codecs.
  The executable decreased from 16,186,850 to 11,627,244 bytes (28.2%).
- Validation: 23 tests passed on Linux/Xvfb and Windows Python 3.12.10/Wine64;
  the rebuilt executable passed the Windows-message-loop smoke test. ZIP
  integrity passed; it contains only nup-gui.exe. Rebuilt tracked release files.

## Devcontainer restoration and repository isolation (2026-11-10)

- Moved `bad-devcontainer/` back to `.devcontainer/`, retaining the bounded
  apt/pip waits and the existing Yarn source repair.
- Confirmed branch `gui` tracks `origin/gui` at `voluptuary/nup-gui`.
  Removed the additional upstream remote and explicitly selected origin for
  pushes. No merkin-agent references were found in working files or Git
  remote settings. All subsequent repository work targets voluptuary/nup-gui.
- Read AGENTS.md and the existing recovery history before making changes.
- Removed Wine32 and the i386 architecture setup from the restored image;
  the build uses extracted Windows x64 Python with a win64 prefix. Updated
  bootstrap instructions and the build script dependency message accordingly.
- Validation: Docker image build and post-create passed as vscode, with no
  foreign package architectures installed. Built the complete Windows x64
  executable in a fresh Wine64 prefix and passed the GUI message-loop smoke
  test. ZIP integrity passed. Wine 8 emitted a missing syswow64/rundll32.exe
  initialization warning but completed the build and smoke test successfully.
  Package downloads decreased from 348 MB to 177 MB in this comparison.
- JSON parsing, shell syntax checks, and git diff --check passed. The live
  Codespace rebuild remains a separate action that disconnects the session.

## Codespace startup repair (2026-11-09)

- Restored `.devcontainer/` from the user-provided `bad-.devcontainer/`
  backup; removed the backup afterward at the user’s explicit request.
- Reproduced the original Dockerfile failing with apt exit 100: the Python
  3.12 Bookworm base image's Yarn source lacks signing key
  `62D54FD4003F6525`. Removed the unused `yarn.list` before apt update while
  retaining Debian signature verification.
- Kept multiarch Wine and Xvfb in the image; removed the duplicate apt install
  from postCreateCommand. Workspace setup now uses a separate shell script
  with noninteractive pip, bounded network retries, and a 180-second limit.
  Added apt download timeouts/retries.
- The available recovery log also records an unrelated default-image Git LFS
  feature failure against a Codespaces-managed post-commit hook. That hook
  was preserved; the restored custom configuration does not request LFS.
- Validation: original image build reproduced apt exit 100; repaired image built,
  post-create completed as vscode, NUP/zstandard imports and Wine/Xvfb checks
  passed. All five existing Python tests passed. Live Codespace rebuild remains
  a separate user action because it disconnects the active session.
- Updated AGENTS.md with the diagnosis, validation commands, log locations,
  and the Windows build behavior of the checked-in build script.

## Metadata and GUI repair (2026-11-09)

- Corrected zero-based TLV IDs to the literal 1-based SPEC values. Added
  detection for identifiable earlier shifted packages and preservation of
  unknown/duplicate metadata when editing.
- Added a shared application metadata reader, localized fallbacks, and NACP
  title/publisher/display-version parsing instead of filename/version guesses,
  including modern compressed language slots. CLI packing shares these defaults.
- Fixed missing GUI imports and the missing publisher argument in atomic
  packing. Create NUP now keeps imported values and manual edits.
- Added Pillow for bounded JPEG/PNG thumbnails, managed temporary icon files,
  wrapped status text, consistent entries and preview sizing, and a source
  preview in the NUP copy dialog. Copy work runs off the UI thread and verifies
  the target before reporting success.
- Added `.nup-metadata.json` preservation of raw metadata and package identity
  across extraction/repacking, including localized/unknown/duplicate TLVs.
  Tracks generated artwork to preserve the original NUP tree on repack.
- NUP-to-NUP copying includes application NACP/localized records while leaving
  source bytes, target content, and target package identity metadata intact.
- Validation: 19 tests passed under Xvfb, including live GUI import, JPEG and
  PNG previews, manual edits through Create NUP, asynchronous copy, literal
  on-disk metadata IDs, legacy migration, and complete raw-metadata/tree round
  trips. The same 19 tests passed under Windows Python 3.12.10 in Wine with
  no tracebacks or Tk callback errors. The final x64 executable built, opened,
  processed Windows messages, and closed cleanly in the executable smoke test.
  ZIP integrity passed and the archive contains only nup-gui.exe.
- Repaired the Wine build: fresh Wine 8 reported Windows 7, which the Python
  installer rejected. After selecting a newer Windows version, Python's WMI
  probes hit Wine's unimplemented VariantToString and launched a debugger
  (Wine bug 55708). The build now extracts the official Python and Tcl/Tk MSI
  components with msitools, configures Windows 10, and omits optional WMI.
  Added msitools to the image and verified the final image builds successfully.
- Put a copy of the repository MIT license inside the Python project and use
  that local path in license-files, avoiding setuptools' outside-project glob
  deprecation and its scheduled future build failure.

## Final validation and publication (2026-11-10)

- Final restored devcontainer image built successfully. Its post-create script
  completed as vscode; NUP CLI, Python imports, Wine, Xvfb, and msiextract were
  checked. The obsolete bad-.devcontainer directory was removed as requested.
- All 19 tests passed on Linux/Xvfb and Windows Python 3.12.10 under Wine,
  including metadata field types, JPEG/PNG previews, asynchronous copying,
  compressed NACP language data, edited values through packing, unknown and
  duplicate TLVs, file bytes, and nonzero package identities through round trips.
  No tracebacks or Tk callback errors remained in the final test logs.
- Built dist/nup-gui.exe and dist/nup-gui-windows-x64.zip. The executable is
  Windows x64; the final smoke test opened it, checked Windows message handling,
  and closed it cleanly. ZIP integrity passed and its sole entry is nup-gui.exe.
  These generated artifacts remain ignored by Git and available in the workspace.
- A live Codespace rebuild was not triggered during the connected session.
  Use Codespaces: Rebuild Container to activate the restored configuration.
  Keep .nup-metadata.json with extracted dumps to retain container-only metadata.

## Pull request cleanup (2026-11-10)

- Reviewed PR #1 against the tested repair branch. Its older GUI implementation
  is superseded by the metadata, round-trip, and Codespace fixes above.
- Removed obsolete descriptions of the broken implementation and transient
  publishing details. Retained the recovery instructions, preservation contract,
  regression tests, and build fixes needed to reproduce the validated result.
- Application and build code are unchanged from the version validated with
  19 tests on Linux/Xvfb and Windows Python/Wine and the executable smoke test.


## Metadata edit dialog layout update (2026-11-10)

- Labeled the metadata source row and aligned its first import button with the
  metadata entry fields. Renamed the third action to “Edit existing .nup metadata”.
- Kept the source and target pickers at the top of that dialog and added the
  editable title, version, publisher, and icon fields beneath them. The bottom
  action now reads “Edit metadata” and applies those values to the selected target
  in one atomic edit.

## Windows GUI build refresh (2026-11-10)

- Rebuilt `dist/nup-gui.exe` and `dist/nup-gui-windows-x64.zip` from the merged
  `gui` source after the metadata editor layout update.
- Confirmed the executable is a Windows x64 GUI binary and the ZIP passes
  integrity checking with only `nup-gui.exe` inside.

## Confirmed source metadata updates (2026-11-10)

- Added an “Update source” action to the existing NUP metadata dialog. It shows
  the changed fields and requests confirmation before editing the selected
  source package, preserving package contents and unrelated metadata.
- Renamed the target action to “Transfer metadata”.
- Rebuilt the Windows x64 executable and ZIP with the updated dialog; the ZIP
  integrity check passed and contains only `nup-gui.exe`.
- Replaced the ZIP asset on the v0.3.0 GitHub release with this refreshed build
  and verified its SHA-256 against the local archive.
