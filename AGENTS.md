# Repository instructions

## Keep this guide current

When you change the Codespace, devcontainer, Windows build, Python version,
dependencies, artifact paths, or validation workflow, update this file in the
same change. Future agents should check these instructions and read `PROGRESS.md`
before building and revise them whenever they learn a recovery step that is not documented here.

## Project map

- Work only in `https://github.com/voluptuary/nup-gui` on branch `gui`.
  Keep `origin` as the only Git remote and use it for all remote operations.
  Temporary branches are allowed for user-requested PRs; merge into `gui`
  and delete them afterward.

- `tools/nup/nup/` is the Python NUP container implementation.
- `tools/nup/windows_gui.py` is the Tkinter desktop GUI entry point.
- `tools/nup/build_windows.ps1` is the native Windows build script.
- `tools/nup/build_wine.sh` builds the Windows executable from Linux using
  Windows Python and PyInstaller under Wine.
- Use the default GitHub Codespaces image and the terminal setup below.
  The former custom configuration is available in Git at `73ab130:.devcontainer/`.
- `dist/nup-gui.exe` and `dist/nup-gui-windows-x64.zip` are generated build
  outputs. The dist directory is ignored for new files, but these two release
  artifacts are currently tracked; rebuilding modifies them. Rebuild them when
  needed; do not assume uncommitted builds survive a Codespace deletion.

Python packaging files live in `tools/nup/`. Run the test suite from the repo
root with:

```sh
PYTHONPATH=tools/nup python -m unittest discover -s tools/nup/tests -v
```

## Set up a Codespace without a custom devcontainer

1. Open the Codespace for `voluptuary/nup-gui` on branch `gui`. From the
   repository root run `git status --short --branch`, `git remote -v`, and
   `git log -5 --oneline`. Read `PROGRESS.md` for the build and recovery
   history. Preserve uncommitted work before switching or replacing a Codespace.
2. Use **Default configuration** when creating a Codespace. A new Codespace
   uses the selected branch's committed files, so check whether that revision
   still contains an active `.devcontainer/devcontainer.json` or root
   `.devcontainer.json` before creating it. Select **Default configuration**
   explicitly if GitHub offers a choice. For future Codespaces to pick the
   default automatically, the branch must have the active configuration
   removed in Git. If an existing Codespace opens in recovery mode and
   its terminal works, use the same manual setup below.
   If the terminal is unusable, save accessible work and logs, then open a
   Codespace with the default configuration.
   [GitHub Codespaces default configuration](https://docs.github.com/en/codespaces/setting-up-your-project-for-codespaces/adding-a-dev-container-configuration/introduction-to-dev-containers#using-the-default-dev-container-configuration)
3. Check `node --version` and `npm --version` in the Codespace terminal.
   The default image supplies both. If they are missing from PATH, open a
   fresh Bash terminal. If needed, load the preinstalled nvm and select an
   installed version.

   ```sh
   export NVM_DIR="${NVM_DIR:-/usr/local/share/nvm}"
   . "$NVM_DIR/nvm.sh"
   nvm use default
   node --version
   npm --version
   ```

   If nvm has no usable Node version, run `nvm install --lts`. If
   `nvm.sh` is absent, use the official nvm installation instructions, then
   install an LTS release. Node is a workspace tool. NUP itself has no Node
   package setup. For editor tooling, install **Python** (`ms-python.python`)
   and **Pylance** (`ms-python.vscode-pylance`) in the Codespace's VS Code
   Extensions view if needed.
   [nvm installation and usage](https://github.com/nvm-sh/nvm#installing-and-updating)
4. Install the Linux system dependencies from the terminal. These commands
   target the default Ubuntu Codespace and also work on Debian with a
   distribution Python of at least 3.11.

   ```sh
   sudo apt-get -o Acquire::Retries=3 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 update
   sudo DEBIAN_FRONTEND=noninteractive apt-get \
     -o Acquire::Retries=3 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 \
     install -y --no-install-recommends \
     ca-certificates curl git unzip file python3 python3-venv python3-tk \
     wine wine64 xvfb xauth msitools
   ```

   Wine64 is sufficient for the Windows x64 build. If apt reports
   `NO_PUBKEY 62D54FD4003F6525` from the old Python image's Yarn repository,
   confirm that `/etc/apt/sources.list.d/yarn.list` is the failing source.
   If Yarn is unused, rename that file to `yarn.list.disabled` and retry
   `apt-get update`. Keep apt signature verification enabled.
   On Ubuntu 24.04, check the x64 Wine loader with
   `/usr/lib/wine/wine64 --version` and the MSI extractor with
   `msiextract --version`.
5. From the repository root, create a virtual environment with the system
   interpreter so it picks up the matching `python3-tk`. The Codespace's
   PATH may select a different Python. Ubuntu 24.04 supplies Python 3.12
   at `/usr/bin/python3`.

   ```sh
   /usr/bin/python3 --version
   /usr/bin/python3 -m venv "$HOME/.venvs/nup-gui"
   . "$HOME/.venvs/nup-gui/bin/activate"
   python -m pip install --no-input --timeout 30 --retries 2 \
     --upgrade "pip>=26.2" "setuptools>=84.1"
   python -m pip install --no-input --timeout 30 --retries 2 -e ./tools/nup
   python -m pip check
   nup --help
   ```

   In a new shell, reactivate the environment with
   `. "$HOME/.venvs/nup-gui/bin/activate"`. In VS Code, select
   `~/.venvs/nup-gui/bin/python` with **Python: Select Interpreter**. Repeat
   the terminal setup after replacing the Codespace or rebuilding an image
   that no longer has the manual installs.
6. Verify Tk and the Python dependencies, then run the full suite with a
   display.

   ```sh
   xvfb-run -a python -c 'import tkinter, nup, PIL, zstandard; root = tkinter.Tk(); root.destroy()'
   PYTHONPATH=tools/nup xvfb-run -a python -m unittest discover -s tools/nup/tests -v
   ```

For a startup failure, save
`/workspaces/.codespaces/.persistedshare/creation.log` and
`/workspaces/.codespaces/shared/unifiedPostCreateOutput.json` if present.
A fallback rebuild can replace both. If the default image's Git LFS setup
reports `Hook already exists: post-commit`, preserve the Codespaces-managed
hook. Inspect the creation log and feature configuration before retrying.
This repository has no LFS attributes.

## Build the Windows executable from the terminal

Build explicitly from the repository root when a Windows artifact is needed.
Run on an x86-64 Linux Codespace. The first build initializes the 64-bit
Wine prefix and downloads the Windows build dependencies.

```sh
WINEPREFIX="$HOME/.cache/nup-wine64" tools/nup/build_wine.sh
```

Use a fresh prefix if an existing prefix was created as 32-bit. Leave the old
prefix intact. Wine 8 and 9 can warn about a missing `syswow64/rundll32.exe`
during 64-bit prefix initialization. The x64 build can proceed if the
registry setup completes successfully.
If Windows Python reports `init_sys_streams` with `[WinError 6] Invalid handle`
when build output is redirected to a file, rerun the command directly in the
terminal.

The script downloads the official Windows Python 3.12.10 x64 `core`, `exe`,
`lib`, and `tcltk` MSI components and extracts them on Linux with
`msiextract` (msitools). It configures a Windows 10 prefix, removes the
optional `_wmi` module from the temporary runtime to work around Wine 8's
missing VariantToString, and patches CopyFile2 during dependency installation.
It uses `xvfb-run` when no display is available and sets
`WINEDLLOVERRIDES="mscoree,mshtml="`.

Source installs require Python 3.11+, Zstandard and Pillow 13+. Build isolation
requires setuptools 84.1+. The manual setup and Windows build scripts upgrade
pip to 26.2+ and setuptools to 84.1+ before installing project dependencies.
Both Windows builds require PyInstaller 6.22.3+.

The Wine build cache defaults to `${XDG_CACHE_HOME:-$HOME/.cache}/nup-windows-build`.
`NUP_WIN_BUILD_DIR` can select a different private directory. The script refuses
symlinks, directories writable by others, and nonempty directories without its
`.nup-build-root` marker. Select a fresh private directory instead of adding a
marker to an unrelated directory. Old `/tmp/nup-windows-build` runtimes can be
left intact. Use the new cache's `python/python.exe` for Windows test/smoke runs.
The native PowerShell build stops on pip failures before deleting build outputs.

The build uses Windows Python 3.12.10 and follows PyInstaller options:
one-file, windowed, no UPX, collect `zstandard`, bundle the GUI icon, and
exclude unused SSL and WMI modules. Set
`PYINSTALLER_ZLIB_COMPRESSION_LEVEL=9` for maximum internal archive compression.
Exclude Pillow AVIF and WebP plugins/native codecs: GUI artwork accepts JPEG
and PNG (including those stored as .dat). Keep JPEG/PNG preview tests passing.

## Build outputs and checks

The Wine build writes:

- `dist/nup-gui.exe` — Windows x64 GUI executable.
- `dist/nup-gui-windows-x64.zip` — ZIP containing only `nup-gui.exe`.

Check the executable architecture and ZIP, then smoke-test the built GUI
with the Windows Python and Wine prefix used by the build.

```sh
file dist/nup-gui.exe
unzip -t dist/nup-gui-windows-x64.zip
unzip -l dist/nup-gui-windows-x64.zip
NUP_WIN_PYTHON="${NUP_WIN_BUILD_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/nup-windows-build}/python/python.exe"
NUP_WINE_BIN=/usr/lib/wine/wine64
if [ ! -x "$NUP_WINE_BIN" ]; then
  NUP_WINE_BIN="$(command -v wine)"
fi
WINEARCH=win64 WINEPREFIX="$HOME/.cache/nup-wine64" WINEDEBUG=-all \
  WINEDLLOVERRIDES="mscoree,mshtml=" xvfb-run -a "$NUP_WINE_BIN" \
  "$NUP_WIN_PYTHON" tools/nup/smoke_gui.py dist/nup-gui.exe
```

Use your chosen `WINEPREFIX` here if it differs from the build example.

The NUP application icon is stored in metadata TLV `0x0003`. Packing accepts
explicit `-i/--icon` or detects common artwork and Switch `icon_*.dat` files;
GUI packaging (`nup-gui`) also supports auto-discovering metadata from dumps,
importing metadata from other `.nup` packages or dumps, editing/replacing metadata
items, format validation for icon files, uniform entry sizing (`width=45`), and
right-click context menus (`Cut`, `Copy`, `Paste`, `Select All`). Keep metadata
injection and unpack extraction behavior aligned across the CLI and GUI. Legacy packages
without artwork must remain extractable and should report a missing-artwork
warning rather than losing their package tree.

## Metadata preservation and GUI validation

- Metadata blocks are not guaranteed to follow file extents. Edits must preserve
  every live extent at its original offset, extended header bytes, and unknown
  trailing bytes. Reclaim only a contiguous metadata-only suffix beyond all
  file extents and the TOC; otherwise append updated metadata. Patch the header
  and TOC at their actual offsets in the temporary copy, validate, then replace
  the original. Do not use the first metadata offset as the end of file data.

- TLV IDs are the literal SPEC.md values, NPDM `0x0001` through localized
  icons `0x000A`, with source-package path `0x000B`. Never use zero-based IDs.
  When editing, migrate recognized shifted metadata across the whole container.
  BananaNative uses a type-zero marker in either the base or newest update to
  choose the numbering for both. Check staged blocks against the intended
  literal IDs and payloads before replacement. **Update source** also checks
  the displayed values, allowing fallback metadata to surface when clearing a
  default field.
  Repacking a dump migrates shifted blocks before applying metadata overrides,
  mixing layouts, adding packages, or splitting the container. An unmodified
  round trip of a consistently numbered package set retains its raw blocks.
- Extraction writes `.nup-metadata.json` at the dump root. Keep this file with
  the dump: it preserves raw per-package metadata blocks (including unknown
  and duplicate records), package IDs, versions, and flags for repacking.
  Generated control artwork is tracked so unchanged preview assets do not
  become extra content on repack. A missing package or invalid manifest must
  fail rather than silently discard preserved data.
- NUP-to-NUP imports copy application metadata (including NACP and complete
  localized sets), preserve target content/NPDM/build IDs/provenance/unknown
  records, and leave the source unchanged. Missing source fields preserve
  target values; an empty source must not report success.
- Keep `tools/nup/LICENSE` synchronized with the repository MIT license; Python
  packaging must use a license path inside `tools/nup/`.
- Pillow is a runtime dependency for JPEG/PNG previews, including `.dat`
  artwork. Both Windows build scripts install it through the NUP package.
- Run the full suite with a display to include GUI import/create/copy checks:

  ```sh
  PYTHONPATH=tools/nup xvfb-run -a python -m unittest discover -s tools/nup/tests -v
  ```

  GUI tests run on Windows without requiring DISPLAY and on Linux with DISPLAY.
  A headless Linux run is not full GUI validation. Wine cannot create real
  symlinks in the current environment; two symlink tests skip there and run
  on Linux, while Windows reparse-attribute handling is tested separately.
  Set `PYTHONPATH=tools/nup` when running the source suite with Windows Python
  under Wine to select the current checkout. The Wine build runtime contains
  an installed snapshot of NUP from its last executable build.
  For Docker checks use `docker run --init` so Xvfb receives startup signals;
  running xvfb-run itself as PID 1 can wait indefinitely for readiness.
  The Windows executable can be smoke-tested under Wine with
  `tools/nup/smoke_gui.py` using the installed Windows Python. Build artifacts
  are currently tracked release files; rebuilt workspace copies must be downloaded
  separately unless published.

## GUI metadata editor and diagnostics

- Use a common 900×510 default/minimum window size for all radio modes.
  Switching modes must preserve the current window dimensions, including a
  user-resized window.
- Metadata editing is the third radio mode in the main window; keep it inline
  and retain source/target fields and edits when switching modes. Transfer is
  the rightmost action; all editor buttons use the same width. Both source
  updates and target transfers require a contextual confirmation showing paths
  and changes before writing; cancelling must leave both packages unchanged.
- Artwork previews use identical fixed 112×112 pixel boxes and 96×96 maximum
  thumbnails, preserving aspect ratio. Keep both pack and metadata editor
  previews square when resizing, empty, loaded, or showing an error.
- Packing, extraction, source updates, and metadata transfers use the same
  progress-bar style and start/stop helpers. Metadata edits use an indeterminate
  bar during editing and verification; hide it on success and failure, and do
  not show it for cancelled confirmations.
- The GUI appends UTF-8 diagnostics and exception tracebacks to `error.log`
  beside the frozen executable (working directory when running from source).
  If that location is unwritable, use `%LOCALAPPDATA%/NUP Packager/error.log`
  on Windows or `~/.local/state/NUP Packager/error.log` otherwise. Error dialogs
  show the selected log path. Configure logging without creating/opening a log
  or making fallback directories; the first error lazily opens the first writable
  destination. Successful runs leave existing log bytes and modification times
  unchanged. Preserve existing log entries; logs are ignored.
- Special characters such as `:`, `&`, and `$` are metadata text, passed directly
  to Python APIs. Windows filename restrictions still apply to selected paths.
  In release notes, use the phrase "special characters" instead of literal
  character examples, to avoid Markdown rendering problems.

## Adversarial validation and consumer compatibility

- See AUDIT.md and audit/ for findings, coverage, consumer revisions, and scan
  inventories. The safety changes retain NUP v1, literal metadata IDs, raw/zstd
  codecs, extent alignment, package identities, and game bytes.
- CLI tree/flat extraction validates paths before writes and requires an empty
  non-link destination. It never overwrites existing files. Windows filename
  restrictions apply to filesystem extraction, not native NUP virtual labels.
- Dump packing rejects links, junctions and special files, checks source bytes
  against the hashing pass, creates outputs exclusively, and removes incomplete
  files it owns. Source tree depth is limited to 256 levels.
- Readers validate counts, references, region overlaps, reserved fields, tree
  cycles and ordering before traversal. File reads and deep verification share
  streaming hash/size checks. Zstandard windows are limited to 256 MiB, and
  previews to JPEG/PNG decoding with 16 million pixels; neither changes stored
  image bytes or the container format. No total extraction disk quota is imposed.
- Preserve opaque trailing metadata bytes as permitted by SPEC section 5.
  Metadata edits use unique sibling files and validate application metadata
  before replacement. Detect concurrent replacements/changes; compare ctime
  only on POSIX because Windows/Wine stat/fstat disagree about its meaning.
- Missing imported application fields preserve target values. Unedited source
  TLVs retain literal bytes, including whitespace. Target selection must retain
  existing manual edits; long preview labels are bounded without truncating fields.
- Optional interoperability checks require supplied consumer source checkouts,
  a C/C++ compiler with OpenSSL/Zstandard headers, a JDK, and Python with Pillow,
  zstandard, capstone, lz4 and compression.zstd (or backports.zstd):

  ```sh
  PYTHONPATH=tools/nup python tools/nup/check_consumers.py \
    --banana-root /path/to/BananaNative --fritchii-root /path/to/Fritchii \
    --report /tmp/nup-consumer-results.json
  ```

  This runs actual consumer reader/preparation checks with synthetic data and
  minimal host adapters, not a game boot or a full emulator/APK build. An optional
  `--baseline-root` accepts a pre-audit tools/nup checkout for binary comparisons.
- CI builds/tests `gui`, PRs targeting `gui`, and release tags on native Windows.
  Actions are pinned to official release commits; the token has contents-read permission,
  checkout does not persist credentials, and the uploaded artifact is the GUI ZIP.
