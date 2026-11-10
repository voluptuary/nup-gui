"""Read regular dump files without following links or blocking on special files."""
from __future__ import annotations

import os
import stat
from . import format as F


def is_link(info) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, 'st_file_attributes', 0) & 0x400)


def open_source(path: str):
    info = os.lstat(path)
    if is_link(info) or not stat.S_ISREG(info.st_mode):
        raise F.NupError(f'source must be a regular file without links: {path!r}')
    flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
    descriptor = os.open(path, flags)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise F.NupError(f'source is not a regular file: {path!r}')
        return os.fdopen(descriptor, 'rb')
    except BaseException:
        os.close(descriptor)
        raise
