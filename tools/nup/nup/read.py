"""NUP reader: validated parsing and integrity checking.

Reader conformance (SPEC §6.1): validate superblock, verify TOC SHA-256
before trusting TOC-derived values, bounds-check every offset/size, treat
title_id/version/NPDM/NACP as opaque, reject unknown codecs and flags.
Tree traversal, metadata access, and extraction live in .access.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import io
import mmap
import os
import struct
from typing import IO, TYPE_CHECKING

from . import format as F
from .errors import OperationCancelled

if TYPE_CHECKING:
    from collections.abc import Callable

    from types import TracebackType


MAX_ZSTD_WINDOW = 256 << 20


class _MappedSliceReader:
    """File-like view over one extent in an mmap, without copying the extent."""

    __slots__ = ("_mapping", "_offset", "_size", "_position")

    def __init__(self, mapping: mmap.mmap | bytes, offset: int, size: int) -> None:
        self._mapping = mapping
        self._offset = offset
        self._size = size
        self._position = 0

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            size = self._size - self._position
        size = min(size, self._size - self._position)
        start = self._offset + self._position
        self._position += size
        return self._mapping[start:start + size]

    def readable(self) -> bool:
        return True


def _check_cancel(cancel: Callable[[], bool] | None) -> None:
    if cancel is not None and cancel():
        raise OperationCancelled("operation cancelled")


@dataclass(frozen=True, slots=True)
class PackageInfo:
    index: int
    title_id: int
    kind: F.Kind
    version: int
    flags: int
    root_dir: int
    exefs_dir: int
    romfs_dir: int
    meta_offset: int
    meta_size: int

    @property
    def kind_name(self) -> str:
        return F.KIND_NAMES.get(self.kind, f"kind{self.kind}")

    @property
    def version_str(self) -> str:
        return f"{self.version >> 16}.{(self.version >> 8) & 0xFF}.{self.version & 0xFF}"


@dataclass(frozen=True, slots=True)
class NodeRef:
    """A child reference: is_dir + index into the respective array."""
    is_dir: bool
    index: int
    name: bytes


class NupReader:
    __slots__ = ("path", "_fh", "_mm", "super", "dir_count", "file_count", "pool", "packages", "files", "dirs", "children")
    def __init__(self, path: str, cancel: Callable[[], bool] | None = None) -> None:
        self.path = path
        self._fh = open(path, "rb")
        self._mm: mmap.mmap | bytes = b""
        try:
            try:
                self._mm = mmap.mmap(self._fh.fileno(), 0, access=mmap.ACCESS_READ)
            except ValueError:  # empty file
                self._mm = b""
            self.super = F.parse_super(self._mm[:F.HEADER_SIZE])
            real_size = os.fstat(self._fh.fileno()).st_size
            if self.super["file_size"] != real_size:
                raise F.NupError(
                    f"file_size {self.super['file_size']} != actual {real_size}")
            if self.super["toc_offset"] != self.super["header_size"]:
                raise F.NupError("toc_offset does not match header_size")
            if self.super["toc_size"] < F._toc_head_s.size:
                raise F.NupError("TOC truncated")
            if self.super["blob_offset"] > real_size:
                raise F.NupError("blob_offset beyond file end")
            if self.super["blob_offset"] < self.super["toc_offset"] + self.super["toc_size"]:
                raise F.NupError("blob region overlaps TOC")
            if self.super["blob_offset"] % F.EXTENT_ALIGN:
                raise F.NupError("blob_offset not 16-byte aligned")

            toc_start = self.super["toc_offset"]
            raw_toc = self._mm[toc_start:toc_start + self.super["toc_size"]]
            if hashlib.sha256(raw_toc).digest() != self.super["toc_sha256"]:
                raise F.NupError("TOC SHA-256 mismatch - file corrupt or tampered")
            self._parse_toc(raw_toc, cancel)
            self._check_bounds(cancel)
        except BaseException:
            # Never leak an open handle/mmap: on Windows it locks the file
            # against rename/delete until GC.
            self.close()
            raise

    def close(self) -> None:
        mm = self._mm
        if isinstance(mm, mmap.mmap):
            mm.close()
        self._mm = b""
        self._fh.close()

    def __enter__(self) -> "NupReader":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    # ---- TOC parsing ----

    def _parse_toc(self, toc: bytes, cancel: Callable[[], bool] | None = None) -> None:
        magic, pkg_count, dir_count, file_count, pool_off, pool_size, _r = \
            F._toc_head_s.unpack_from(toc, 0)
        if _r:
            raise F.NupError("TOC reserved bytes not zero")
        if magic != F.TOC_MAGIC:
            raise F.NupError(f"bad TOC magic {magic!r}")
        if pkg_count != self.super["package_count"]:
            raise F.NupError("package_count mismatch between superblock and TOC")
        need = (F._toc_head_s.size + pkg_count * F.PKG_SIZE
                + dir_count * F.DIR_SIZE + file_count * F.FILE_SIZE)
        if len(toc) < need:
            raise F.NupError("TOC truncated")
        if pool_off + pool_size > len(toc) or pool_off < need:
            raise F.NupError("string pool out of TOC bounds")

        self.dir_count = dir_count
        self.file_count = file_count
        self.pool = toc[pool_off:pool_off + pool_size]

        pos = F._toc_head_s.size
        self.packages: list[PackageInfo] = []
        for i in range(pkg_count):
            if i % 1024 == 0:
                _check_cancel(cancel)
            p = F.parse_pkg(toc, pos)
            pos += F.PKG_SIZE
            self.packages.append(PackageInfo(
                index=i, title_id=p.title_id, kind=F.Kind(p.kind), version=p.version,
                flags=p.flags, root_dir=p.root_dir, exefs_dir=p.exefs_dir,
                romfs_dir=p.romfs_dir, meta_offset=p.meta_offset,
                meta_size=p.meta_size))

        self.dirs: list[tuple[bytes, int, int]] = []  # (name, first_child, child_count)
        for i in range(dir_count):
            if i % 1024 == 0:
                _check_cancel(cancel)
            off, ln, first, count, _r2 = F._dir_s.unpack_from(toc, pos)
            pos += F.DIR_SIZE
            if _r2:
                raise F.NupError("directory reserved bytes not zero")
            self.dirs.append((self._pool_str(off, ln), first, count))

        # (name, size, sha256, ext_off, ext_size, codec)
        self.files: list[tuple[bytes, int, bytes, int, int, F.Codec]] = []  
        for i in range(file_count):
            if i % 1024 == 0:
                _check_cancel(cancel)
            (off, ln), size, sha, eoff, esz, codec = F.parse_file(toc, pos)
            pos += F.FILE_SIZE
            self.files.append((self._pool_str(off, ln), size, sha, eoff, esz, codec))

        slot_end = pool_off
        if (slot_end - pos) % 4:
            raise F.NupError("children array not 4-byte aligned")
        self.children = list(struct.unpack_from(f"<{(slot_end - pos) // 4}I", toc, pos))

    def _pool_str(self, off: int, ln: int) -> bytes:
        if off + ln > len(self.pool):
            raise F.NupError("string reference out of pool bounds")
        value = self.pool[off:off + ln]
        try:
            value.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise F.NupError("node name is not UTF-8") from exc
        return value

    def _check_bounds(self, cancel: Callable[[], bool] | None = None) -> None:
        file_size = self.super["file_size"]
        blob_start = self.super["blob_offset"]
        for i, (name, size, sha, eoff, esz, codec) in enumerate(self.files):
            if i % 1024 == 0:
                _check_cancel(cancel)
            if codec == F.CODEC_RAW and esz != size:
                raise F.NupError(f"raw extent size mismatch for {name!r}")
            if size == 0:
                continue
            if eoff < blob_start or eoff + esz > file_size:
                raise F.NupError(f"extent out of bounds for file {name!r}")
            if eoff % F.EXTENT_ALIGN:
                raise F.NupError(f"extent not {F.EXTENT_ALIGN}-aligned for {name!r}")
        slot_total = len(self.children)
        ranges = []
        for i, (name, first, count) in enumerate(self.dirs):
            if i % 1024 == 0:
                _check_cancel(cancel)
            if first + count > slot_total:
                raise F.NupError(f"child range out of bounds for dir {name!r}")
            if count:
                ranges.append((first, first + count))
        cursor = 0
        for first, end in sorted(ranges):
            if first != cursor:
                raise F.NupError("child slot ranges overlap or leave gaps")
            cursor = end
        if cursor != slot_total:
            raise F.NupError("unreferenced child slots")
        if any(cid >= self.dir_count + self.file_count for cid in self.children):
            raise F.NupError("child reference out of bounds")
        for _, first, count in self.dirs:
            names = [self.dirs[cid][0] if cid < self.dir_count else self.files[cid - self.dir_count][0]
                     for cid in self.children[first:first + count]]
            if any(a >= b for a, b in zip(names, names[1:])):
                raise F.NupError("directory children must be sorted with unique names")
        # Check every component, including orphan subgraphs, without recursion.
        colors = bytearray(self.dir_count)
        for root in range(self.dir_count):
            if colors[root]:
                continue
            stack = [(root, False)]
            while stack:
                _check_cancel(cancel)
                node, leaving = stack.pop()
                if leaving:
                    colors[node] = 2
                    continue
                if colors[node] == 1:
                    raise F.NupError("directory graph contains a cycle")
                if colors[node] == 2:
                    continue
                colors[node] = 1
                stack.append((node, True))
                _, first, count = self.dirs[node]
                stack.extend((cid, False) for cid in self.children[first:first + count]
                             if cid < self.dir_count)
        for p in self.packages:
            if p.root_dir >= self.dir_count:
                raise F.NupError(f"package {p.index}: root_dir out of bounds")
            for d in (p.exefs_dir, p.romfs_dir):
                if d != F.NO_DIR and d >= self.dir_count:
                    raise F.NupError(f"package {p.index}: exefs/romfs dir out of bounds")
            if p.meta_size and (p.meta_offset + p.meta_size > file_size):
                raise F.NupError(f"package {p.index}: meta block out of bounds")
            if p.flags & ~F.PKG_FLAG_STANDALONE_UPDATE:
                raise F.NupError(f"package {p.index}: unknown package flags {p.flags:#x}")
        toc_end = self.super["toc_offset"] + self.super["toc_size"]
        regions = []
        for _, size, sha, offset, stored, codec in self.files:
            if size:
                regions.append((offset, offset + stored, ("extent", size, sha, int(codec))))
        from .meta import parse_block
        for package in self.packages:
            if package.meta_size:
                if package.meta_offset < toc_end:
                    raise F.NupError("metadata overlaps header or TOC")
                regions.append((package.meta_offset, package.meta_offset + package.meta_size, ("metadata",)))
        previous = None
        for region in sorted(set(regions)):
            if previous and region[0] < previous[1] and region != previous:
                raise F.NupError("file extents or metadata regions overlap inconsistently")
            previous = region
        for package in self.packages:
            if package.meta_size:
                parse_block(bytes(self._mm[package.meta_offset:package.meta_offset + package.meta_size]))
        # SPEC §3.1.2: update packages need a base in the same container, or
        # the standalone_update flag (record flags, offset 0x19, bit 0).
        if sum(p.kind == F.KIND_BASE for p in self.packages) > 1:
            raise F.NupError("container has more than one base package")
        has_base = any(p.kind == F.KIND_BASE for p in self.packages)
        for i, p in enumerate(self.packages):
            if i % 1024 == 0:
                _check_cancel(cancel)
            if (p.kind == F.KIND_UPDATE and not has_base
                    and not (p.flags & F.PKG_FLAG_STANDALONE_UPDATE)):
                raise F.NupError(
                    f"package {p.index}: update without base in container and "
                    f"standalone_update flag not set")

    # ---- member access ----

    def node_name(self, ref: NodeRef) -> bytes:
        if ref.is_dir:
            return self.dirs[ref.index][0]
        return self.files[ref.index][0]

    def file_info(self, file_index: int) -> tuple[bytes, int, bytes, int, int, F.Codec]:
        return self.files[file_index]

    def copy_file(
        self,
        file_index: int,
        output: IO[bytes],
        cancel: Callable[[], bool] | None = None,
    ) -> int:
        """Stream an extracted file to output, checking cancellation per chunk."""
        name, size, expected_hash, extent_offset, extent_size, codec = self.files[file_index]
        digest = hashlib.sha256()
        written = 0

        def check_cancel() -> None:
            if cancel is not None and cancel():
                raise OperationCancelled("operation cancelled")

        def write_chunk(chunk: bytes) -> None:
            nonlocal written
            if written + len(chunk) > size:
                raise F.NupError(f"size overflow while extracting {name!r}")
            position = 0
            while position < len(chunk):
                check_cancel()
                count = output.write(memoryview(chunk)[position:])
                if not isinstance(count, int) or count <= 0 or count > len(chunk) - position:
                    raise OSError("short or invalid output write")
                position += count
            digest.update(chunk)
            written += len(chunk)

        if codec == F.CODEC_RAW:
            if extent_size != size:
                raise F.NupError(
                    f"raw extent size {extent_size} != file size {size} for {name!r}")
            while written < size:
                check_cancel()
                chunk = self._mm[extent_offset + written:
                                 extent_offset + min(size, written + (4 << 20))]
                if not chunk:
                    raise F.NupError(f"short read for {name!r}")
                write_chunk(chunk)
        elif codec == F.CODEC_ZSTD:
            import zstandard

            source = _MappedSliceReader(self._mm, extent_offset, extent_size)
            try:
                header = self._mm[extent_offset:extent_offset + min(extent_size, 18)]
                frame = zstandard.get_frame_parameters(header)
                if frame.content_size != size:
                    raise F.NupError(f"Zstandard frame size does not match file size for {name!r}")
                if frame.window_size > MAX_ZSTD_WINDOW:
                    raise F.NupError("Zstandard frame exceeds the 256 MiB decoder window limit")
                with zstandard.ZstdDecompressor(max_window_size=MAX_ZSTD_WINDOW // 1024).stream_reader(
                    source, read_size=4 << 20, closefd=False,
                ) as decompressed:
                    while True:
                        check_cancel()
                        chunk = decompressed.read(min(4 << 20, size - written + 1))
                        if not chunk:
                            break
                        write_chunk(chunk)
            except zstandard.ZstdError as exc:
                raise F.NupError(f"decompression failed for {name!r}: {exc}") from exc
        else:
            raise F.NupError(f"unknown codec {codec}")

        check_cancel()
        if written != size:
            raise F.NupError(f"size mismatch for {name!r}: {written} != {size}")
        if digest.digest() != expected_hash:
            raise F.NupError(f"SHA-256 mismatch for {name!r}")
        return written

    def read_file(self, file_index: int) -> bytes:
        # Use the same bounded decoder and hash checks as streaming extraction.
        output = io.BytesIO()
        self.copy_file(file_index, output)
        return output.getvalue()
