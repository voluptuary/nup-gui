# NUP - NX Package Format

A container for unencrypted Nintendo Switch / Switch 2 game dumps. 
Spec sheet: **[SPEC.md](SPEC.md)**

```
base/            updates/458752/      dlc/040074a01bf13001/0/
├─ exefs/        ├─ exefs/            └─ romfs/          ──►  game.nup
└─ romfs/        └─ romfs/
```

NUP is a clean-room container format for **unencrypted NX (Nintendo Switch 1/2) game dumps**.

It stores ExeFS program files and full RomFS trees, this means it stores updates, base content 
and addons in one compressed file.

It can be used for either Switch 1 or Switch 2 games, of course that means you would have to
decrypt the game and package it into an nup. (which i am not aware of for Switch 1 Games).

## Tools

`tools/nup/` is the Python reference implementation (Python 3.11 or newer):

```
pip install ./tools/nup          # or: PYTHONPATH=tools/nup python3 -m nup.cli
nup --help                       # overview of every subcommand
```

### Windows executable

The repository builds a Windows x64 GUI executable. On Windows, run
`tools/nup/build_windows.ps1`; from the configured Linux devcontainer, run
`tools/nup/build_wine.sh`. Both write `dist/nup-gui.exe` and
`dist/nup-gui-windows-x64.zip`, which contains only the GUI executable. The
GitHub Actions workflow uploads this GUI ZIP, and releases publish that ZIP at
[GitHub Releases](https://github.com/voluptuary/nup-gui/releases).

The GUI is a single-file Tkinter application packaged with PyInstaller. Its
background worker calls the NUP packer directly, so it does not launch
PowerShell or require a separate Python installation. The executable uses the
supplied NUP icon, and the build excludes unused OpenSSL/TLS modules without
UPX packing.

For the desktop interface, launch `nup-gui.exe`, choose the dump parent folder
and output `.nup` path, then select **Create NUP**. The packaging panel accepts
an optional icon file, game title, and display version. If no icon is selected,
the packer looks for common PNG/JPEG artwork names in the source and package
`control/` folders, including Switch `icon_*.dat` assets. The GUI packages the same
directory layouts as the `nup pack` command, preserves `.listing` files for
round trips, and shows per-file progress while it runs. Select **Unpack NUP**
to restore the package into `base/`, `updates/`, and `dlc/` folders. The
packager stores the original package paths so add-on directory indexes are
restored too; unpacking older NUPs without that metadata uses generated indexes.
Select **Cancel** to stop at a safe file or data-chunk boundary. Incomplete
output is staged separately and removed, leaving the source and any existing
destination untouched.

### Recreating the Codespace

The `.devcontainer/` definition describes the Python and Wine build environment.
After it is committed and pushed, a recreated Codespace can rebuild that
environment from the repository. Commit or push source changes and any
important build artifacts before deleting a Codespace; the devcontainer
definition cannot recover uncommitted files from a deleted workspace.

`pack` accepts the documented `base/`, `updates/`, and `dlc/` bundle layout,
or a single content directory containing `exefs/` and/or `romfs/`. The dump
must already be decrypted; this tool packages files and does not decrypt game
content.

### Packing a dump

`pack` discovers packages by directory layout:

| directory | becomes |
|---|---|
| `base/` containing `exefs/` and/or `romfs/` | the `base` package |
| `updates/<decimal version>/` with `exefs/` and/or `romfs/` | one `update` package per version |
| `dlc/<16-hex title id>/<index>/` with `exefs/` and/or `romfs/` | one `addon` package per index |
| a bare content dir (no `base/`) | a single `base` package |
| `updates/` without `base/` | update-only dump; every update is flagged `standalone_update` |

Anything else inside `dlc/` (non-hex names, index dirs without `exefs/`/`romfs/`) is skipped.

```
nup pack <dump_dir> <out.nup> [options]
```

| option | meaning |
|---|---|
| `--level N` | zstd level, default 3. Each file is compressed individually; files that don't shrink are stored raw. |
| `--title-id HEX` | override the base title ID (16 hex digits). Otherwise it is read from `exefs/main.npdm`. |
| `--display-version V` | human version string (e.g. `1.2.3`) stored in metadata; takes authority over the packed numeric version. |
| `--publisher NAME` | publisher string in metadata. |
| `--name NAME` | title name, default language. |
| `--lang-name LANG=NAME` | localized title, repeatable: `--lang-name ja=ゼルダの伝説` |
| `-i, --icon PATH` | icon image, default language (JPEG/PNG); auto-detected from artwork/control files when omitted. |
| `--lang-icon LANG=PATH` | localized icon, repeatable. |
| `--keep-listings` | keep dump-tool `.listing` files (excluded by default). |
| `-q` | quiet; don't print progress. |

Notes:

- `pack` refuses to overwrite an existing output file.
- Name/icon/display-version/publisher metadata is attached to the `base` package, or to the
  first package in base-less dumps.
- The icon is stored in the NUP application metadata block (TLV `0x0003`) and
  extraction materializes it as `base/control/icon.jpg` or `icon.png`. Existing
  control files in the package tree are preserved; iconless packages produce a
  missing artwork warning when unpacked.
- The build ID (NSO ModuleId - what mods/cheats tooling keys on) is derived automatically
  from `exefs/main` when present.
- Output is deterministic for a given dump and zstd version.

Examples:

```
nup pack ./dump game.nup
nup pack ./dump game.nup --name "Super Game" --lang-name ja=スーパーゲーム \
    --icon icon.png --display-version 1.2.3 --publisher "Acme"
```

### Inspecting

```
nup info game.nup              # packages: kind, title ID, versions, metadata, build ID
nup info game.nup --tree       # also print the exefs/romfs trees
nup info game.nup --tree --depth 4
nup list game.nup              # every file node: index, size, codec (raw/zstd)
```

### Extracting

```
nup extract game.nup out_dir                      # the first package
nup extract game.nup out_dir --package update     # first package of that kind
nup extract game.nup out_dir --package 2          # package by index (see `info`)
nup extract game.nup out_dir --subtree romfs      # only that subtree, relative to package root
```

Extracted files are decompressed automatically (zstd) and land with their tree structure.

### Editing metadata after packing

`edit` rewrites a package's meta block - contents and extents are untouched,
the file is validated before an atomic replace.

```
nup edit game.nup --name "Renamed Game" --publisher "Acme" --display-version 1.2.4
nup edit game.nup --icon new_icon.png
nup edit game.nup --lang-name ja=新しい名前 --lang-icon ja=icon_ja.dat
nup edit game.nup --lang-name ja=                    # empty value removes the ja title
nup edit game.nup --clear-icon --clear-display-version
nup edit game.nup --package update --name "Patch Notes Name"
nup edit game.nup --package 2 --name "By Index"
```

| flag | meaning |
|---|---|
| `--name` / `--clear-name` | set / remove the default-language title (TLV 0x0005) |
| `--publisher` / `--clear-publisher` | set / remove the publisher (TLV 0x0006) |
| `--display-version` / `--clear-display-version` | set / remove the display version (TLV 0x0004) |
| `--icon` / `--clear-icon` | set / remove the default-language icon (TLV 0x0003) |
| `--lang-name LANG=NAME` | set a localized title; empty `NAME` removes it (TLV 0x0009) |
| `--lang-icon LANG=PATH` | set a localized icon; empty `PATH` removes it (TLV 0x000A) |
| `--package` | target: kind name (`base`/`update`/`addon`) or index; default is wherever the app metadata lives, else `base` |

Merge semantics: flags you provide override, everything else is preserved - including the
NPDM, build ID and source-dump provenance. `edit` cannot change `title_id`, `version`,
`kind` or flags (those are package-record fields covered by the UUID).

### Verifying

```
nup verify game.nup            # structure + TOC hash + per-file SHA-256 recompute
nup verify game.nup --fast     # structure only (no per-file hashing)
nup verify game.nup --max-problems 50
```

Exit codes: `0` ok, `1` verification failed (problems listed), `2` malformed input.

## Layout

```
SPEC.md            format specification
tools/nup/       reference implementation (Python)
```

### Preserving metadata during conversions

When extracting a NUP, keep the generated `.nup-metadata.json` file beside the
`base`, `updates`, and `dlc` folders. It preserves the original package identity
and raw metadata, including localized titles/icons and unknown records. Repack
that complete dump to retain them. Unchanged artwork generated from metadata
is excluded from the repacked content tree; original content files are retained.
Explicitly supplied metadata replaces the corresponding values.

The GUI imports title, publisher, display version, and JPEG/PNG artwork from NUP
metadata, with localized fallbacks. Dump imports read those text fields from
`control.nacp` rather than guessing from folder names or numeric package versions.
The NACP layout follows [libnx's NACP definition](https://github.com/switchbrew/libnx/blob/master/nx/include/switch/nacp.h).

“Import from .nup to .nup” previews and copies application metadata, including
NACP and localized records, then verifies the target. It leaves the source
unchanged and preserves the target's content files, NPDM, build IDs, provenance,
and unknown metadata. Fields absent from the source keep their target values.
