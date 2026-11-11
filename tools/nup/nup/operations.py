"""Transactional, cancellable pack and full-dump extraction operations."""

from __future__ import annotations

import os
import tempfile
from typing import TYPE_CHECKING

from .access import extract_dump
from .errors import OperationCancelled
from .pack import pack
from .read import NupReader

if TYPE_CHECKING:
    from collections.abc import Callable
    from .discover import FileObj


def _require_missing(path: str) -> None:
    if os.path.lexists(path):
        raise FileExistsError(f"refusing to overwrite existing output: {path}")


def pack_atomic(
    output: str,
    source: str,
    *,
    icon: str | None = None,
    name: str | None = None,
    display_version: str | None = None,
    publisher: str | None = None,
    progress: Callable[[int, int, FileObj], None] | None = None,
    cancel: Callable[[], bool] | None = None,
    keep_listings: bool = True,
) -> None:
    """Pack to a sibling work file, publishing output only after success."""
    target = os.path.abspath(output)
    parent = os.path.dirname(target)
    if not os.path.isdir(parent):
        raise FileNotFoundError(f"output parent folder does not exist: {parent}")
    _require_missing(target)
    if cancel is not None and cancel():
        raise OperationCancelled("operation cancelled")

    work_parent = parent
    source_root = os.path.abspath(source)
    try:
        if os.path.commonpath((source_root, parent)) == source_root:
            source_parent = os.path.dirname(source_root)
            if source_parent != source_root:
                work_parent = source_parent
    except ValueError:  # different Windows drives
        pass

    with tempfile.TemporaryDirectory(prefix=".nup-pack-", dir=work_parent) as work_dir:
        staged = os.path.join(work_dir, "package.nup")
        pack(staged, source, keep_listings=keep_listings,
             icons={None: icon} if icon else None,
             names={None: name} if name else None,
             display_version=display_version or None, publisher=publisher or None,
             progress=progress, cancel=cancel)
        with NupReader(staged, cancel=cancel):
            pass
        if cancel is not None and cancel():
            raise OperationCancelled("operation cancelled")
        _require_missing(target)
        if os.name == "nt":
            # Windows rename refuses to replace an existing destination and
            # works on filesystems that do not support hard links.
            os.rename(staged, target)
        else:
            # POSIX rename replaces existing paths, so use an exclusive link.
            os.link(staged, target)


def unpack_atomic(
    source: str,
    output: str,
    *,
    progress: Callable[[int, int, str], None] | None = None,
    cancel: Callable[[], bool] | None = None,
) -> int:
    """Extract into a sibling work folder, publishing it only after success."""
    target = os.path.abspath(output)
    parent = os.path.dirname(target)
    if not os.path.isdir(parent):
        raise FileNotFoundError(f"output parent folder does not exist: {parent}")
    _require_missing(target)
    if cancel is not None and cancel():
        raise OperationCancelled("operation cancelled")

    with tempfile.TemporaryDirectory(prefix=".nup-unpack-", dir=parent) as work_dir:
        with NupReader(source, cancel=cancel) as reader:
            written = extract_dump(reader, work_dir, progress, cancel)
        if cancel is not None and cancel():
            raise OperationCancelled("operation cancelled")
        _require_missing(target)
        os.rename(work_dir, target)
        return written
