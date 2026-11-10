# Repository instructions

## Keep this guide current

When you change the Codespace, devcontainer, Windows build, Python version,
dependencies, artifact paths, or validation workflow, update this file in the
same change. Future agents should check these instructions and read `PROGRESS.md`
before building and revise them whenever they learn a recovery step that is not documented here.

## Project map

- Work only in `https://github.com/voluptuary/nup-gui` on branch `gui`.
  Keep `origin` as the only Git remote. Do not push, pull, commit, or open
  pull requests against `merkin-agent/nup-gui`.

- `tools/nup/nup/` is the Python NUP container implementation.
- `tools/nup/windows_gui.py` is the Tkinter desktop GUI entry point.
- `tools/nup/build_windows.ps1` is the native Windows build script.
- `tools/nup/build_wine.sh` builds the Windows executable from Linux using
  Windows Python and PyInstaller under Wine.
- `.devcontainer/` defines the Codespace Python and Wine build environment.
- `dist/nup-gui.exe` and `dist/nup-gui-windows-x64.zip` are generated build
  outputs and are ignored by Git. Rebuild them when needed; do not assume they
  survive a Codespace deletion.

Python packaging files live in `tools/nup/`. Run the test suite from the repo
root with:

```sh
PYTHONPATH=tools/nup python -m unittest discover -s tools/nup/tests -v
```

## Cold-start or recover a damaged Codespace

1. Reopen the repository Codespace and check `git status`, the current branch,
   and recent commits before changing files. A deleted or corrupted workspace
   can contain uncommitted work that Git cannot recover; inspect available
   branches and remotes before assuming a file was never present.
2. If `.devcontainer/` is missing or damaged, recover any committed version
   first, for example with `git show <commit>:.devcontainer/Dockerfile` and
   `git show <commit>:.devcontainer/devcontainer.json`. The repository's
   devcontainer installs Python 3.12, 64-bit Wine, and
   Xvfb for headless Windows builds. After restoring it, use **Codespaces:
   Rebuild Container** so the Dockerfile and `postCreateCommand` run. The
   active configuration must be in `.devcontainer/`, and the Dockerfile must
   be named exactly `Dockerfile` because `devcontainer.json` refers to that
   path. A backup folder such as `bad-devcontainer/` is not discovered by
   Codespaces.
   The upstream Python image's unused `/etc/apt/sources.list.d/yarn.list`
   caused a reproduced build failure: `NO_PUBKEY 62D54FD4003F6525` and apt
   exit 100. Keep its removal before `apt-get update`; NUP does not use Yarn.
   Never bypass apt signature checks to work around this failure.
   System packages are installed only in the Dockerfile. Do not add apt,
   Windows Python installation, or Wine initialization to lifecycle commands.
   `.devcontainer/post-create.sh` installs the editable Python package with a
   three-minute limit and bounded pip network retries. The Dockerfile bounds
   apt network waits and retries; a cold Wine image build still needs
   time to download and unpack packages. Wine32 and i386 are not required:
   the complete executable build and GUI smoke test pass with Wine64 alone.
   A fresh Wine 8 prefix can warn about missing syswow64/rundll32.exe during
   initialization; this warning did not prevent the x64 build or smoke test.
   Inspect the creation log to distinguish
   active build progress from a stalled lifecycle command.

   Recovery logs are at
   `/workspaces/.codespaces/.persistedshare/creation.log` and lifecycle status at
   `/workspaces/.codespaces/shared/unifiedPostCreateOutput.json`. These may only
   describe the current recovery image, not the original failed custom build.
   On 2026-11-09 the recovery image's automatic Git LFS setup failed with
   `Hook already exists: post-commit` against a Codespaces-managed hook. Do not
   overwrite that hook with `git lfs update --force`. The custom image does not
   request the Git LFS feature; this repository currently has no LFS attributes.
   If this error recurs in a default/recovery image, preserve the hook and
   inspect the feature configuration before retrying lifecycle commands.

   Validate changes before rebuilding the live Codespace:

   ```sh
   docker build --progress=plain -t nup-devcontainer-check .devcontainer
   docker run --rm --init --user vscode -v "$PWD:/workspace" -w /workspace \
     nup-devcontainer-check bash .devcontainer/post-create.sh
   ```

3. If the devcontainer cannot be rebuilt, bootstrap the host environment on
   Ubuntu/Debian with:

   ```sh
   sudo apt-get update
   sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
     ca-certificates curl git unzip file wine wine64 xvfb xauth msitools
   python3 -m pip install --user -e ./tools/nup
   ```

   Wine needs a 64-bit prefix for the Windows Python installer. If the default
   `~/.cache/nup-wine` was created as 32-bit, leave it intact and select a new
   prefix for the build, such as `~/.cache/nup-wine64`.
4. Build from the repository root:

   ```sh
   WINEPREFIX="$HOME/.cache/nup-wine64" tools/nup/build_wine.sh
   ```

   The build script downloads the official Python 3.12.10 x64 `core`, `exe`,
   `lib`, and `tcltk` MSI components and extracts them on Linux with
   `msiextract` (msitools). It does not execute the MSI installer under Wine.
   It configures a Windows 10 prefix, disables the optional `_wmi` module
   in the temporary build runtime (Wine 8 lacks VariantToString), and patches
   CopyFile2 only while installing dependencies. It runs headlessly under
   `xvfb-run` with `WINEDLLOVERRIDES="mscoree,mshtml="`. Windows executable
   builds are explicit actions and must not run during Codespace creation.

The build uses Windows Python 3.12.10 and follows PyInstaller options:
one-file, windowed, no UPX, collect `zstandard`, bundle the GUI icon, and
exclude unused SSL and WMI modules.

## Build outputs and checks

The Wine build writes:

- `dist/nup-gui.exe` — Windows x64 GUI executable.
- `dist/nup-gui-windows-x64.zip` — ZIP containing only `nup-gui.exe`.

Check the output with `file dist/nup-gui.exe` and
`unzip -l dist/nup-gui-windows-x64.zip`.

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

- TLV IDs are the literal SPEC.md values, NPDM `0x0001` through localized
  icons `0x000A`, with source-package path `0x000B`. Never use zero-based IDs.
  Readers recognize the earlier shifted layout when NPDM/icon/provenance bytes
  identify it. Edits migrate recognized legacy types without losing payloads.
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

  GUI tests skip without DISPLAY; a headless-only run is not full GUI validation.
  For Docker checks use `docker run --init` so Xvfb receives startup signals;
  running xvfb-run itself as PID 1 can wait indefinitely for readiness.
  The Windows executable can be smoke-tested under Wine with
  `tools/nup/smoke_gui.py` using the installed Windows Python. Build artifacts
  remain ignored by Git and must be downloaded separately from the workspace.
