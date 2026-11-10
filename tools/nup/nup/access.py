"""NUP tree access: traversal, metadata accessors, and extraction.

Convenience layer over a parsed NupReader: directory traversal and path
resolution, per-package meta/localized accessors, and subtree extraction.
Functions take the reader as their first argument.
"""

from __future__ import annotations

import os
import re
import sys
import stat
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from . import format as F
from .icons import image_extension, is_icon_filename, is_supported_image
from .errors import OperationCancelled
from . import meta as M
from .read import NodeRef

if TYPE_CHECKING:
    from .read import NupReader, PackageInfo

    from collections.abc import Callable


def find_package(
    r: NupReader,
    kind: int | None = None,
    title_id: int | None = None,
    version: int | None = None,
) -> PackageInfo | None:
    for p in r.packages:
        if kind is not None and p.kind != kind:
            continue
        if title_id is not None and p.title_id != title_id:
            continue
        if version is not None and p.version != version:
            continue
        return p
    return None


def iter_children(r: NupReader, dir_index: int) -> list[NodeRef]:
    _, first, count = r.dirs[dir_index]
    out = []
    for slot in range(first, first + count):
        cid = r.children[slot]
        if cid >= r.dir_count:
            fi = cid - r.dir_count
            out.append(NodeRef(False, fi, r.files[fi][0]))
        else:
            out.append(NodeRef(True, cid, r.dirs[cid][0]))
    return out


def find_child(r: NupReader, dir_index: int, name: bytes) -> NodeRef | None:
    children = iter_children(r, dir_index)
    lo, hi = 0, len(children)
    while lo < hi:
        mid = (lo + hi) // 2
        if children[mid].name < name:
            lo = mid + 1
        else:
            hi = mid
    if lo < len(children) and children[lo].name == name:
        return children[lo]
    return None


def meta_records(r: NupReader, pkg: PackageInfo) -> list[tuple[int, bytes]]:
    block = bytes(r._mm[pkg.meta_offset:pkg.meta_offset + pkg.meta_size])
    return list(M.parse_block(block).items())


def _localized(r: NupReader, pkg: PackageInfo, tlv_type: int) -> dict[bytes, bytes]:
    out: dict[bytes, bytes] = {}
    for t, payload in meta_records(r, pkg):
        if t == tlv_type:
            out.update(M.decode_localized(payload))
    return out


def localized_titles(r: NupReader, pkg: PackageInfo) -> dict[bytes, bytes]:
    """BCP-47 tag (lowercase bytes) -> UTF-8 title name. SPEC §5.1, TLV 0x0009."""
    return _localized(r, pkg, F.TLV_LOCALIZED_TITLES)


def localized_icons(r: NupReader, pkg: PackageInfo) -> dict[bytes, bytes]:
    """BCP-47 tag (lowercase bytes) -> image bytes. SPEC §5.1, TLV 0x000A."""
    return _localized(r, pkg, F.TLV_LOCALIZED_ICONS)


def app_meta(r: NupReader, pkg: PackageInfo) -> dict[int, bytes]:
    """TLV type -> payload, preferring the base (or first) package's block."""
    return dict(meta_records(r, pkg))


def build_id(r: NupReader, pkg: PackageInfo) -> bytes | None:
    """32-byte ModuleId from meta TLV 0x0007, or None if absent (SPEC §5).

    Bytes 0x40..0x60 of the package's `main` (NSO0/NRO0 header); only the
    first 0x14 are significant in SDK-built titles."""
    payload = app_meta(r, pkg).get(F.TLV_BUILD_ID)
    if payload is not None and len(payload) != 32:
        raise F.NupError(f"build ID TLV payload is {len(payload)} bytes, expected 32")
    return payload


def resolve_path(r: NupReader, pkg: PackageInfo, relpath: str) -> NodeRef | None:
    """Resolve a '/'-separated path from the package root."""
    cur = NodeRef(True, pkg.root_dir, b"")
    for part in relpath.split("/"):
        if not part:
            continue
        if not cur.is_dir:
            return None
        nxt = find_child(r, cur.index, part.encode("utf-8"))
        if nxt is None:
            return None
        cur = nxt
    return cur


def _empty_destination(dest: str) -> None:
    if os.path.lexists(dest):
        info = os.lstat(dest)
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise F.NupError("extraction destination cannot be a link or junction")
    os.makedirs(dest, exist_ok=True)
    if os.listdir(dest):
        raise F.NupError("extraction destination must be empty")


def _validate_extract_tree(r: NupReader, root: int, cancel=None) -> None:
    stack = [root]
    visited = set()
    while stack:
        if cancel is not None and cancel():
            raise OperationCancelled("operation cancelled")
        current = stack.pop()
        if current in visited:
            raise F.NupError("directory tree contains a cycle or alias")
        visited.add(current)
        names = set()
        for child in iter_children(r, current):
            name = child.name.decode("utf-8", "surrogateescape")
            if not _valid_windows_component(name):
                raise F.NupError(f"unsafe or Windows-incompatible path component {child.name!r}")
            if name.casefold() in names:
                raise F.NupError("case-insensitive extraction path collision")
            names.add(name.casefold())
            if child.is_dir:
                stack.append(child.index)


def extract_flat(r: NupReader, dest: str) -> int:
    names = []
    for index, record in enumerate(r.files):
        name = record[0].decode("utf-8", "surrogateescape")
        if not _valid_windows_component(name) or not _valid_windows_component(f"{index:05d}_{name}"):
            raise F.NupError(f"unsafe flat extraction name {record[0]!r}")
        names.append(f"{index:05d}_{name}")
    _empty_destination(dest)
    for index, name in enumerate(names):
        with open(os.path.join(dest, name), "xb") as output:
            r.copy_file(index, output)
    return len(names)


def extract_tree(
    r: NupReader,
    dest: str,
    dir_index: int,
    progress: Callable[[int, NodeRef], None] | None = None,
    cancel: Callable[[], bool] | None = None,
) -> int:
    """Extract a directory subtree to dest. Returns number of files written."""
    _validate_extract_tree(r, dir_index, cancel)
    _empty_destination(dest)
    n = 0
    stack = [(dir_index, dest)]
    while stack:
        di, dpath = stack.pop()
        os.makedirs(dpath, exist_ok=True)
        for child in iter_children(r, di):
            if cancel is not None and cancel():
                raise OperationCancelled("operation cancelled")
            cpath = os.path.join(dpath, child.name.decode("utf-8", "surrogateescape"))
            if child.is_dir:
                stack.append((child.index, cpath))
            else:
                with open(cpath, "xb") as fh:
                    r.copy_file(child.index, fh, cancel)
                n += 1
                if progress:
                    progress(n, child)
    return n


def write_control_icon(icon_data: bytes, package_dest: str) -> bool:
    """Materialize a valid metadata icon as a conventional control asset."""
    extension = image_extension(icon_data)
    if extension is None:
        print("unpack: warning: application icon metadata is not a supported JPEG/PNG image",
              file=sys.stderr)
        return False
    control_dir = os.path.join(package_dest, "control")
    os.makedirs(control_dir, exist_ok=True)
    icon_path = os.path.join(control_dir, "icon" + extension)
    if os.path.exists(icon_path):
        return False
    with open(icon_path, "wb") as stream:
        stream.write(icon_data)
    return True


def has_control_icon(package_dest: str) -> bool:
    return any(
        is_supported_image(os.path.join(root, name))
        for root, _dirs, filenames in os.walk(package_dest)
        for name in filenames if is_icon_filename(name)
    )


def extract_dump(
    r: NupReader,
    dest: str,
    progress: Callable[[int, int, str], None] | None = None,
    cancel: Callable[[], bool] | None = None,
) -> int:
    """Extract every package into the canonical base/updates/dlc layout.

    Original canonical package paths are restored from optional provenance
    metadata. Older NUP files without it get canonical paths synthesized from
    their package records.
    """
    targets: list[tuple[PackageInfo, str]] = []
    addon_indexes: dict[int, int] = {}
    for pkg in r.packages:
        if cancel is not None and cancel():
            raise OperationCancelled("operation cancelled")
        fallback: str
        if pkg.kind == F.KIND_BASE:
            fallback = "base"
        elif pkg.kind == F.KIND_UPDATE:
            fallback = f"updates/{pkg.version}"
        elif pkg.kind == F.KIND_ADDON:
            index = addon_indexes.get(pkg.title_id, 0)
            addon_indexes[pkg.title_id] = index + 1
            fallback = f"dlc/{pkg.title_id:016x}/{index}"
        else:
            raise F.NupError(
                f"cannot map package kind {pkg.kind_name!r} to the standard dump layout")
        source_path = next(
            (payload for kind, payload in meta_records(r, pkg)
             if kind == F.TLV_SOURCE_PACKAGE_PATH),
            None,
        )
        relpath = fallback
        if source_path:
            try:
                candidate = source_path.decode("utf-8")
            except UnicodeDecodeError:
                candidate = ""
            parts = PurePosixPath(candidate).parts
            valid = (
                not PurePosixPath(candidate).is_absolute()
                and candidate == "/".join(parts)
                and all(_valid_windows_component(part) for part in parts)
            )
            if pkg.kind == F.KIND_BASE:
                valid = valid and candidate == "base"
            elif pkg.kind == F.KIND_UPDATE:
                valid = (valid and len(parts) == 2 and parts[0] == "updates"
                         and re.fullmatch(r"[0-9]{1,10}", parts[1]) is not None
                         and int(parts[1]) == pkg.version)
            else:
                valid = (valid and len(parts) == 3 and parts[0] == "dlc"
                         and re.fullmatch(r"[0-9a-fA-F]{16}", parts[1]) is not None
                         and int(parts[1], 16) == pkg.title_id
                         and re.fullmatch(r"[0-9]{1,10}", parts[2]) is not None)
            if valid:
                relpath = os.path.join(*parts)
        targets.append((pkg, relpath))

    # Validate all package paths and NUP tree components before writing any files.
    target_names: set[str] = set()
    total = 0
    reachable_dirs: set[int] = set()
    reachable_files: set[int] = set()
    for pkg, relpath in targets:
        if relpath.casefold() in target_names:
            raise F.NupError(f"multiple packages map to {relpath!r}")
        target_names.add(relpath.casefold())
        stack = [pkg.root_dir]
        visited_dirs: set[int] = set()
        while stack:
            if cancel is not None and cancel():
                raise OperationCancelled("operation cancelled")
            di = stack.pop()
            if di in visited_dirs:
                raise F.NupError(f"package {pkg.index}: directory tree contains a cycle or alias")
            visited_dirs.add(di)
            reachable_dirs.add(di)
            children = iter_children(r, di)
            folded_names: set[str] = set()
            for child in children:
                if cancel is not None and cancel():
                    raise OperationCancelled("operation cancelled")
                name = child.name.decode("utf-8", "surrogateescape")
                if not _valid_windows_component(name):
                    raise F.NupError(f"unsafe or Windows-incompatible path component {child.name!r}")
                if name.casefold() in folded_names:
                    raise F.NupError(
                        f"Windows case-insensitive path collision in directory {di}: {name!r}")
                folded_names.add(name.casefold())
                if child.is_dir:
                    stack.append(child.index)
                else:
                    reachable_files.add(child.index)
                    total += 1

    if len(reachable_dirs) != r.dir_count:
        raise F.NupError("NUP contains unreachable directories; refusing to omit them")
    if len(reachable_files) != r.file_count:
        raise F.NupError("NUP contains unreachable files; refusing to omit them")

    destination = os.path.abspath(dest)
    os.makedirs(destination, exist_ok=True)
    if os.listdir(destination):
        raise F.NupError("destination folder must be empty")

    done = 0
    extracted_packages: list[tuple[PackageInfo, str]] = []
    for pkg, relpath in targets:
        package_dest = os.path.join(destination, relpath)
        extracted_packages.append((pkg, package_dest))

        def report(_package_count: int, child: NodeRef) -> None:
            nonlocal done
            done += 1
            if progress:
                name = child.name.decode("utf-8", "replace")
                progress(done, total, os.path.join(relpath, name))

        extract_tree(r, package_dest, pkg.root_dir, report, cancel)

    # NUP application artwork lives in meta TLV 0x0003. Materialize it as a
    # conventional control icon too, so dump-oriented tools retain the asset.
    from .application import read_application
    icon_data = read_application(r).icon or None
    control_icon_written = False
    generated_artwork = []
    if icon_data is not None:
        base_dest = next((path for pkg, path in extracted_packages
                          if pkg.kind == F.KIND_BASE),
                         extracted_packages[0][1] if extracted_packages else None)
        if base_dest is not None:
            import hashlib
            control_exists = os.path.isdir(os.path.join(base_dest, "control"))
            control_icon_written = write_control_icon(icon_data, base_dest)
            if control_icon_written:
                generated_artwork.append(dict(
                    path=os.path.relpath(os.path.join(base_dest, "control", "icon" + image_extension(icon_data)), destination).replace(os.sep, "/"),
                    sha256=hashlib.sha256(icon_data).hexdigest(),
                    created_directory=not control_exists))

    if not control_icon_written:
        found_icon_file = any(has_control_icon(package_dest)
                              for _pkg, package_dest in extracted_packages)
        if not found_icon_file and icon_data is None:
            print("unpack: warning: missing artwork metadata (no control icon found)",
                  file=sys.stderr)
    from .roundtrip import write_sidecar
    write_sidecar(r, destination, targets, generated_artwork)
    return done


def _valid_windows_component(name: str) -> bool:
    return bool(
        name and name not in (".", "..")
        and sum(2 if ord(c) > 0xFFFF else 1 for c in name) <= 255
        and name[-1] not in (".", " ")
        and not any(ord(c) < 32 or 0xD800 <= ord(c) <= 0xDFFF
                    or c in '<>:"/\\|?*' for c in name)
        and re.fullmatch(r"(?i:con|prn|aux|nul|conin\$|conout\$|com[1-9¹²³]|lpt[1-9¹²³])",
                        name.partition(".")[0].rstrip(" ")) is None
    )
