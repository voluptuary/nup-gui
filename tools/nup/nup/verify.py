"""NUP structural and streaming content verification."""
from __future__ import annotations

from . import format as F
from .access import app_meta
from .icons import image_extension
from .read import NupReader


class _Discard:
    def write(self, data: bytes) -> int:
        return len(data)


def verify(path: str, deep: bool = False) -> tuple[bool, list[str]]:
    problems = []
    try:
        with NupReader(path) as reader:
            package = next((p for p in reader.packages if p.kind == F.KIND_BASE), reader.packages[0])
            icon = app_meta(reader, package).get(F.TLV_ICON)
            if icon is not None and image_extension(icon) is None:
                problems.append("application icon metadata is not a supported JPEG/PNG image")
            visited = set()
            referenced = set()
            stack = [p.root_dir for p in reader.packages]
            while stack:
                current = stack.pop()
                if current in visited:
                    continue
                visited.add(current)
                _, first, count = reader.dirs[current]
                for child in reader.children[first:first + count]:
                    if child < reader.dir_count:
                        stack.append(child)
                    else:
                        referenced.add(child - reader.dir_count)
            if len(visited) != reader.dir_count:
                problems.append(f"{reader.dir_count - len(visited)} unreachable directories")
            if len(referenced) != reader.file_count:
                problems.append(f"{reader.file_count - len(referenced)} unreferenced file nodes")
            if deep:
                checked = set()
                for index, (name, size, sha, offset, stored, codec) in enumerate(reader.files):
                    identity = (size, sha, offset, stored, codec)
                    if identity in checked:
                        continue
                    try:
                        reader.copy_file(index, _Discard())
                    except F.NupError as exc:
                        problems.append(f"file {index} ({name!r}): {exc}")
                    checked.add(identity)
    except (F.NupError, OSError) as exc:
        problems.append(f"open: {exc}")
    return not problems, problems
