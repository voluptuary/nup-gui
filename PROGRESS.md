# Progress & Change Log

This document records meaningful changes and enhancements made to `nup-gui` and its tooling.

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

## Summary of Changes

1. **Automatic Metadata Discovery & Incorporation**
   - **Technical Explanation**: Enhanced `nup-gui` (`windows_gui.py`) and underlying discovery/packing utilities to automatically scan selected dump folders and `.nup` packages. When a dump folder is selected, it auto-detects application icons via `detect_icon`, infers game titles, and picks up version numbers.

2. **UI Layout Enhancements & Uniform Entry Sizing**
   - **Technical Explanation**: Standardized all `ttk.Entry` fields (`source_entry`, `icon_entry`, `title_entry`, `version_entry`, `publisher_entry`, `output_entry`) to have a uniform width (`width=45`) and height. Relocated the icon row below the title, version, and publisher fields.

3. **Space-Saving Live Icon Thumbnail Preview**
   - **Technical Explanation**: Added a live icon thumbnail preview widget that spans rows 3 to 5 in column 2 (to the right of Game Title, Display Version, and Publisher entry fields), fitting into the interface without increasing row spacing. Traces variable writes on `self.icon` to update dynamically.

4. **Split Metadata Import Buttons & Exact Wording**
   - **Technical Explanation**: Configured three action buttons side-by-side on the same row with exact wording:
     - `"Import from dump"`
     - `"Import from .nup"`
     - `"Import from .nup to .nup"`
   - Implemented field-clearing behavior so fields are reset before importing fresh metadata.

5. **NUP-to-NUP Metadata Copy Dialog Window**
   - **Technical Explanation**: Implemented a dedicated modal window (`tk.Toplevel`) for `"Import from .nup to .nup"` featuring source and target `.nup` file pickers, status updates, and a final `"Copy metadata"` action button leveraging `nup.edit.edit`.

6. **Robust Binary/Text Metadata Validation (`_safe_text`)**
   - **Technical Explanation**: Added strict validation checking during metadata import from NUP packages and dumps to ensure binary image payloads (like JPEG/PNG magic bytes or JFIF headers) are never incorrectly decoded into text fields (title, publisher, display version).

7. **Copy/Paste Context Menus**
   - **Technical Explanation**: Bound right-click context menus (`Cut`, `Copy`, `Paste`, `Select All`) to all editable text entry fields.

8. **Non-Interactive Wine Build Pipeline (`build_wine.sh`)**
   - **Technical Explanation**: Configured `build_wine.sh` to run headlessly under `xvfb-run` with `WINEDLLOVERRIDES="mscoree,mshtml="` to suppress Wine GUI/debugger popups. Applied Python 3.12 `shutil.py` `CopyFile2` bypass for Wine 9 compatibility, enabling reliable, fully non-interactive compilation of `dist/nup-gui.exe` and `dist/nup-gui-windows-x64.zip`.
