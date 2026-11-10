#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${DISPLAY:-}" && -z "${NUP_WINE_XVFB:-}" ]] && command -v xvfb-run >/dev/null 2>&1; then
  export NUP_WINE_XVFB=1
  exec xvfb-run -a -s "-screen 0 1024x768x24" "$0" "$@"
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
build_root="${NUP_WIN_BUILD_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/nup-windows-build}"
python_version="3.12.10"
python_dir="$build_root/python"

dist_dir="$repo_root/dist"
work_dir="$build_root/pyinstaller-build"
wine_bin="/usr/lib/wine/wine64"
if [[ ! -x "$wine_bin" ]]; then
  wine_bin="$(command -v wine || true)"
fi
if [[ ! -x "$wine_bin" ]]; then
  echo "Wine not found. Install wine and wine64, then rerun this script." >&2
  exit 1
fi

# Keep build deletions/downloads out of shared predictable /tmp directories.
# A preexisting nonempty directory must carry our ownership marker.
python3 - "$build_root" <<'PYGUARD'
import os
import stat
import sys
from pathlib import Path
root = Path(sys.argv[1]).absolute()
marker = root / ".nup-build-root"
if root.is_symlink():
    raise SystemExit("build: build directory must not be a symlink")
if root.exists():
    info = root.stat()
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o022:
        raise SystemExit("build: build directory must be owned by this user and not writable by others")
    if any(root.iterdir()) and (marker.is_symlink() or not marker.is_file()
                               or marker.read_text() != "nup-windows-build-v1\n"):
        raise SystemExit("build: nonempty unmarked build directory; select a fresh NUP_WIN_BUILD_DIR")
root.mkdir(mode=0o700, parents=True, exist_ok=True)
marker.write_text("nup-windows-build-v1\n")
for name in ("python", "pyinstaller-build"):
    if (root / name).is_symlink():
        raise SystemExit("build: refusing to delete a symlinked build runtime")
PYGUARD

mkdir -p "$build_root" "$dist_dir"

python3 - "$python_dir" "$work_dir" <<'PY'
import shutil
import sys
from pathlib import Path
for item in map(Path, sys.argv[1:]):
    if item.exists():
        shutil.rmtree(item)
PY

# Extract official Python components on Linux. Running the bundle/MSI engine
# under Wine can fail in propsys.VariantToString or wait on a debugger prompt.
if ! command -v msiextract >/dev/null 2>&1; then
  echo "msiextract not found. Install msitools, then rerun this script." >&2
  exit 1
fi
mkdir -p "$python_dir"
for component in core exe lib tcltk; do
  archive="$build_root/$component.msi"
  curl -fsSL --retry 3 --connect-timeout 30 --max-time 180 \
    "https://www.python.org/ftp/python/${python_version}/amd64/${component}.msi" \
    -o "$archive"
  msiextract -C "$python_dir" "$archive" > "$build_root/$component-extract.log"
done
# Python's optional WMI probes call propsys.VariantToString, absent in Wine 8.
# platform.py has a supported fallback when _wmi is unavailable (Wine bug 55708).
rm -f "$python_dir/DLLs/_wmi.pyd"

winpath() {
  local converted="${1//\//\\}"
  printf 'Z:%s' "$converted"
}

export WINEARCH=win64
export WINEPREFIX="${WINEPREFIX:-$HOME/.cache/nup-wine}"
export WINEDEBUG="${WINEDEBUG:--all}"
export WINEDLLOVERRIDES="mscoree,mshtml="

python_win="$(winpath "$python_dir/python.exe")"
root_win="$(winpath "$repo_root")"
dist_win="$(winpath "$dist_dir")"
work_win="$(winpath "$work_dir")"
icon_win="$(winpath "$repo_root/tools/nup/launcher/assets/NUP_GUI_Packager.ico")"
gui_entry_win="$root_win\\tools\\nup\\windows_gui.py"

# Python 3.12 requires Windows 8.1+, while fresh Wine 8 prefixes default to 7.
timeout --foreground 120s "$wine_bin" reg add 'HKCU\Software\Wine' /v Version /t REG_SZ /d win10 /f

# Disable CopyFile2 in Python 3.12 shutil for Wine 9 compatibility during pip
shutil_file="$python_dir/Lib/shutil.py"
shutil_backup="$build_root/shutil.py.original"
if [[ -f "$shutil_file" ]]; then
  cp "$shutil_file" "$shutil_backup"
  python3 - "$shutil_file" <<'PY'
import sys
from pathlib import Path
path = Path(sys.argv[1])
source = path.read_text(encoding="utf-8")
marker = 'if hasattr(_winapi, "CopyFile2"):'
if source.count(marker) == 1:
    path.write_text(source.replace(marker, 'if False and hasattr(_winapi, "CopyFile2"):'), encoding="utf-8")
PY
fi

restore_shutil() {
  if [[ -f "$shutil_backup" ]]; then
    cp "$shutil_backup" "$shutil_file"
    rm -f "$shutil_backup"
  fi
}
trap restore_shutil EXIT

"$wine_bin" "$python_win" -m ensurepip --upgrade
"$wine_bin" "$python_win" -m pip install --upgrade "pip>=26.2" "setuptools>=84.1" --no-warn-script-location
"$wine_bin" "$python_win" -m pip install "$root_win\\tools\\nup" "pyinstaller>=6.22.3" --no-warn-script-location

restore_shutil
trap - EXIT

mkdir -p "$work_dir"
rm -f "$dist_dir/nup-gui.exe" "$dist_dir/nup-gui-windows-x64.zip"

# Compress embedded archives at the highest zlib level; keep UPX disabled.
export PYINSTALLER_ZLIB_COMPRESSION_LEVEL=9
"$wine_bin" "$python_win" -m PyInstaller \
  --noconfirm --clean --onefile --windowed --noupx \
  --name nup-gui --paths "$root_win\\tools\\nup" --collect-all zstandard \
  --exclude-module PIL.AvifImagePlugin --exclude-module PIL._avif \
  --exclude-module PIL.WebPImagePlugin --exclude-module PIL._webp \
  --exclude-module _hashlib --exclude-module _ssl --exclude-module ssl --exclude-module _wmi \
  --icon "$icon_win" --add-data "${icon_win};assets" \
  --distpath "$dist_win" --workpath "$work_win\\gui" --specpath "$work_win\\gui" \
  "$gui_entry_win"

python3 - "$dist_dir" <<'PY'
import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

dist = Path(sys.argv[1])
with ZipFile(dist / "nup-gui-windows-x64.zip", "w", ZIP_DEFLATED, compresslevel=9) as archive:
    archive.write(dist / "nup-gui.exe", "nup-gui.exe")
PY

file "$dist_dir/nup-gui.exe"
ls -lh "$dist_dir/nup-gui-windows-x64.zip"
