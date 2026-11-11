"""Shared application metadata selection for GUI import, copy, and extraction."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import format as F
from .icons import image_extension
from .meta import decode_localized, package_records
from .read import NupReader

APP_TYPES = (F.TLV_NACP, F.TLV_TITLE_NAME, F.TLV_PUBLISHER, F.TLV_DISPLAY_VERSION,
             F.TLV_ICON, F.TLV_LOCALIZED_TITLES, F.TLV_LOCALIZED_ICONS)


def text_value(payload: bytes | None) -> str:
    if not payload:
        return ""
    try:
        value = payload.decode("utf-8").rstrip("\0").strip()
    except UnicodeDecodeError:
        return ""
    return value if value and all(c.isprintable() for c in value) else ""


def preferred_localized(payload: bytes, *, image: bool = False) -> bytes:
    entries = decode_localized(payload)
    keys = sorted(entries, key=lambda tag: (tag not in (b"en-us", b"en"), tag))
    return next((entries[key] for key in keys
                 if (image_extension(entries[key]) if image else text_value(entries[key]))), b"")


@dataclass
class ApplicationMetadata:
    title: str = ""
    publisher: str = ""
    version: str = ""
    icon: bytes = b""
    records: dict[int, bytes] = field(default_factory=dict)


def from_records(records: dict[int, bytes]) -> ApplicationMetadata:
    valid: dict[int, bytes] = {}
    for kind in APP_TYPES:
        payload = records.get(kind, b"")
        if not payload:
            continue
        if kind == F.TLV_NACP:
            valid[kind] = payload
        elif kind in (F.TLV_TITLE_NAME, F.TLV_PUBLISHER, F.TLV_DISPLAY_VERSION):
            if text_value(payload):
                valid[kind] = payload
        elif kind == F.TLV_ICON:
            if image_extension(payload):
                valid[kind] = payload
        else:
            # Validate framing before preserving the complete localized set.
            preferred_localized(payload, image=kind == F.TLV_LOCALIZED_ICONS)
            valid[kind] = payload
    title = text_value(valid.get(F.TLV_TITLE_NAME))
    if not title and F.TLV_LOCALIZED_TITLES in valid:
        title = text_value(preferred_localized(valid[F.TLV_LOCALIZED_TITLES]))
    icon = valid.get(F.TLV_ICON, b"")
    if not icon and F.TLV_LOCALIZED_ICONS in valid:
        icon = preferred_localized(valid[F.TLV_LOCALIZED_ICONS], image=True)
    nacp = nacp_metadata(valid.get(F.TLV_NACP, b""))
    return ApplicationMetadata(title or nacp.title,
                               text_value(valid.get(F.TLV_PUBLISHER)) or nacp.publisher,
                               text_value(valid.get(F.TLV_DISPLAY_VERSION)) or nacp.version, icon, valid)


def read_application(reader: NupReader) -> ApplicationMetadata:
    records: dict[int, bytes] = {}
    blocks = [bytes(reader._mm[p.meta_offset:p.meta_offset + p.meta_size])
              for p in reader.packages]
    interpreted = package_records(blocks)
    packages = sorted(reader.packages, key=lambda pkg: pkg.kind != F.KIND_BASE)
    for package in packages:
        for kind, payload in from_records(interpreted[package.index][0]).records.items():
            records.setdefault(kind, payload)
    return from_records(records)


def load_application(path: str | Path) -> ApplicationMetadata:
    with NupReader(str(path)) as reader:
        return read_application(reader)


def copy_application(source: str, target: str, *, name: str | None = None,
                     publisher: str | None = None, display_version: str | None = None,
                     icon: str | None = None, clear_name: bool = False,
                     clear_publisher: bool = False, clear_display_version: bool = False,
                     clear_icon: bool = False) -> ApplicationMetadata:
    from .edit import edit
    if Path(source).resolve() == Path(target).resolve():
        raise ValueError("Choose different source and target packages.")
    metadata = load_application(source)
    if not metadata.records:
        raise ValueError("The source has no valid application metadata to copy.")
    # Preserve localized sets and absent target fields; never copy NPDM, build
    # IDs, or provenance from an unrelated game. edit uses atomic replacement.
    target_before = load_application(target)
    # Preserve literal source/target records whenever their effective values
    # already match. Materialize a default only when stale target defaults or
    # replaced fallback records would otherwise change the intended value.
    application_records = dict(metadata.records)
    projected_records = dict(target_before.records)
    projected_records.update(application_records)
    projected = from_records(projected_records)
    if name is None and not clear_name and projected.title != (metadata.title or target_before.title):
        name = metadata.title or target_before.title or None
    if publisher is None and not clear_publisher and projected.publisher != (metadata.publisher or target_before.publisher):
        publisher = metadata.publisher or target_before.publisher or None
    if display_version is None and not clear_display_version and projected.version != (metadata.version or target_before.version):
        display_version = metadata.version or target_before.version or None
    wanted_icon = metadata.icon or target_before.icon
    if wanted_icon and not clear_icon and projected.icon != wanted_icon:
        application_records[F.TLV_ICON] = wanted_icon
    expected_records = dict(target_before.records)
    expected_records.update(application_records)
    for kind, value, clear in (
        (F.TLV_TITLE_NAME, name, clear_name),
        (F.TLV_PUBLISHER, publisher, clear_publisher),
        (F.TLV_DISPLAY_VERSION, display_version, clear_display_version),
    ):
        if clear:
            expected_records.pop(kind, None)
        elif value is not None:
            expected_records[kind] = value.encode("utf-8")
    if clear_icon:
        expected_records.pop(F.TLV_ICON, None)
    elif icon is not None:
        expected_records[F.TLV_ICON] = Path(icon).read_bytes()
    expected = from_records(expected_records)
    def validate(staged: str) -> None:
        actual = load_application(staged)
        if actual.records != expected.records:
            raise F.NupError("Target metadata verification failed before replacing original")
    edit(target, app_records=application_records, name=name, publisher=publisher,
         display_version=display_version, icon=icon, clear_name=clear_name,
         clear_publisher=clear_publisher, clear_display_version=clear_display_version,
         clear_icon=clear_icon, validate=validate)
    return load_application(target)


def nacp_metadata(data: bytes) -> ApplicationMetadata:
    """Read standard NACP UTF-8 language slots and display-version string.

    Layout: libnx nx/include/switch/nacp.h (0x300-byte language entries).
    Do not manufacture a display version from a package's numeric version.
    """
    if len(data) < 0x3070:
        return ApplicationMetadata()
    version = text_value(data[0x3060:0x3070].split(b"\0", 1)[0])
    titles = data[:0x3000]
    count = 16
    # libnx TitlesDataFormat at 0x3215: modern NACP may DEFLATE 32 slots.
    title_format = data[0x3215] if len(data) > 0x3215 else 0
    if title_format:
        if title_format != 1:
            return ApplicationMetadata(version=version)
        import zlib
        size = int.from_bytes(data[:2], "little")
        if not 0 < size <= 0x2FFE:
            return ApplicationMetadata(version=version)
        try:
            decoder = zlib.decompressobj(wbits=-15)
            titles = decoder.decompress(data[2:2 + size], 32 * 0x300 + 1)
            if not decoder.eof or len(titles) != 32 * 0x300:
                return ApplicationMetadata(version=version)
        except zlib.error:
            return ApplicationMetadata(version=version)
        count = 32
    title = publisher = ""
    for index in range(count):
        start = index * 0x300
        name = text_value(titles[start:start + 0x200].split(b"\0", 1)[0])
        author = text_value(titles[start + 0x200:start + 0x300].split(b"\0", 1)[0])
        if not title and name:
            title = name
        if not publisher and author:
            publisher = author
        if title and publisher:
            break
    return ApplicationMetadata(title, publisher, version)


def dump_application(source: Path, package_dirs: list[str]) -> ApplicationMetadata:
    from .icons import detect_icon
    from .roundtrip import read_sidecar
    preserved = read_sidecar(str(source))
    if preserved:
        records = {}
        packages = sorted(preserved["packages"], key=lambda p: p["kind"] != F.KIND_BASE)
        for block_records, _ in package_records([p["raw_block"] for p in packages]):
            for kind, payload in block_records.items():
                records.setdefault(kind, payload)
        return from_records(records)
    metadata = ApplicationMetadata()
    for directory in [source, *(Path(path) for path in package_dirs)]:
        for relative in ("control.nacp", "control/control.nacp", "romfs/control.nacp",
                         "romfs/control/control.nacp"):
            path = directory / relative
            if path.is_file():
                candidate = nacp_metadata(path.read_bytes())
                if candidate.title or candidate.version:
                    metadata = candidate
                    break
        if metadata.title or metadata.version:
            break
    icon = detect_icon(str(source), package_dirs)
    if icon:
        metadata.icon = Path(icon).read_bytes()
    return metadata
