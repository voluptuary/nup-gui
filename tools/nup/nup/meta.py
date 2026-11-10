"""NUP package meta block: TLV assembly for per-package metadata.

Builds the per-package meta block (NPDM, build ID, provenance) and the
application-level TLVs (names, icons, display version, SPEC §5.1) that
ride along in the base package's block. Serialization is deterministic:
records are sorted by TLV type and written without padding.
"""

from __future__ import annotations

import struct
import re
from typing import Protocol

from . import format as F


class MetaSource(Protocol):
    """What meta_block needs of a package: its dump-derived metadata."""

    npdm: bytes | None
    build_id: bytes | None
    source_path: str | None


def read_file(path: str) -> bytes:
    from .sourceio import open_source
    with open_source(path) as fh:
        return fh.read()


def parse_block(block: bytes, *, normalize: bool = True) -> dict[int, bytes]:
    """TLV type -> payload for one meta block (first occurrence wins)."""
    out: dict[int, bytes] = {}
    pos = 0
    while pos + 8 <= len(block):
        t, _r, size = F._tlv_s.unpack_from(block, pos)
        if _r or pos + 8 + size > len(block):
            raise F.NupError("meta TLV overruns block")
        out.setdefault(t, bytes(block[pos + 8:pos + 8 + size]))
        pos += 8 + size
    if not normalize:
        return out
    # Releases before the SPEC numbering fix wrote types 0..9 instead of 1..10.
    # Only migrate when the bytes identify that layout; never guess from text
    # fields alone. SOURCE_PACKAGE_PATH (0x000B) was already correct.
    from .icons import image_extension
    legacy = 0 in out or image_extension(out.get(2, b"")) is not None
    if not legacy and 7 in out and 8 not in out and len(out[7]) != 32:
        try:
            legacy = bool(out[7]) and out[7].decode("utf-8").isprintable()
        except UnicodeDecodeError:
            pass
    if legacy:
        out = {(t + 1 if 0 <= t <= 9 else t): data for t, data in out.items()}
    return out


def update_block(block: bytes, records: dict[int, bytes]) -> bytes:
    """Change selected TLVs without discarding unknown/duplicate records."""
    previous = parse_block(block)
    legacy = previous != parse_block(block, normalize=False)
    changes = {t for t in previous.keys() | records.keys()
               if previous.get(t) != records.get(t)}
    seen = set()
    out = bytearray()
    pos = 0
    while pos + 8 <= len(block):
        kind, reserved, size = F._tlv_s.unpack_from(block, pos)
        payload = block[pos + 8:pos + 8 + size]
        kind = kind + 1 if legacy and 0 <= kind <= 9 else kind
        if kind not in changes:
            out += F._tlv_s.pack(kind, reserved, size) + payload
        elif kind in records and kind not in seen:
            out += F._tlv_s.pack(kind, 0, len(records[kind])) + records[kind]
        seen.add(kind)
        pos += 8 + size
    for kind in sorted(records.keys() - seen):
        out += F._tlv_s.pack(kind, 0, len(records[kind])) + records[kind]
    # SPEC §5 ends parsing when fewer than eight bytes remain. Keep that
    # opaque tail (including legacy alignment padding) after any new records.
    out += block[pos:]
    return bytes(out)


def serialize_block(records: dict[int, bytes]) -> bytes:
    """Deterministic meta block: records sorted by type, no padding."""
    out = bytearray()
    for t in sorted(records):
        payload = records[t]
        out += F._tlv_s.pack(t, 0, len(payload)) + payload
    return bytes(out)


def decode_localized(payload: bytes) -> dict[bytes, bytes]:
    """Parse a LocalizedRecord sequence (SPEC §5.1) into {lang tag: data}."""
    out: dict[bytes, bytes] = {}
    pos = 0
    while pos < len(payload):
        lang_len = payload[pos]
        pos += 1
        if not lang_len or pos + lang_len + 4 > len(payload):
            raise F.NupError("truncated or empty localized language tag")
        lang = payload[pos:pos + lang_len]
        pos += lang_len
        if not re.fullmatch(rb"[A-Za-z]{1,8}(?:-[A-Za-z0-9]{1,8})*", lang):
            raise F.NupError("invalid localized language tag")
        try:
            lang.decode("ascii")
        except UnicodeDecodeError as exc:
            raise F.NupError("localized language tag is not ASCII") from exc
        (data_len,) = struct.unpack_from("<I", payload, pos)
        pos += 4
        if pos + data_len > len(payload):
            raise F.NupError("localized record overruns TLV")
        if lang.lower() in out:
            raise F.NupError("duplicate localized language tag")
        out[lang.lower()] = payload[pos:pos + data_len]
        pos += data_len
    return out


def merge_app_meta(existing: dict[int, bytes], *, name: str | None = None,
                   publisher: str | None = None, display_version: str | None = None,
                   icon: str | None = None, lang_names: dict[str, str] | None = None,
                   lang_icons: dict[str, str] | None = None,
                   clear_name: bool = False, clear_publisher: bool = False,
                   clear_display_version: bool = False,
                   clear_icon: bool = False) -> dict[int, bytes]:
    """Apply edit flags to existing meta records (TLV type -> payload).

    Provided values override; everything else is preserved. Empty lang
    values remove that language from the localized set; --clear-* drops
    the default-language TLV. Package-level TLVs pass through untouched.
    """
    out = dict(existing)
    if clear_name:
        out.pop(F.TLV_TITLE_NAME, None)
    elif name is not None:
        out[F.TLV_TITLE_NAME] = name.encode("utf-8")
    if clear_publisher:
        out.pop(F.TLV_PUBLISHER, None)
    elif publisher is not None:
        out[F.TLV_PUBLISHER] = publisher.encode("utf-8")
    if clear_display_version:
        out.pop(F.TLV_DISPLAY_VERSION, None)
    elif display_version is not None:
        out[F.TLV_DISPLAY_VERSION] = display_version.encode("utf-8")
    if clear_icon:
        out.pop(F.TLV_ICON, None)
    elif icon is not None:
        out[F.TLV_ICON] = read_file(icon)
    for tlv, changes, read_values in ((F.TLV_LOCALIZED_TITLES, lang_names, False),
                                      (F.TLV_LOCALIZED_ICONS, lang_icons, True)):
        if not changes:
            continue
        loc = {lang.decode("ascii"): data
               for lang, data in decode_localized(out[tlv]).items()} if tlv in out else {}
        for lang, value in changes.items():
            if value == "":
                loc.pop(lang.lower(), None)
            else:
                loc[lang.lower()] = read_file(value) if read_values else value.encode("utf-8")
        if loc:
            out[tlv] = _encode_localized(loc)
        else:
            out.pop(tlv, None)
    return out


def meta_block(pkg: MetaSource, dump_label: str, app_extra: bytes = b"") -> bytes:
    """Serialize one package's meta block (SPEC §5)."""
    recs: list[tuple[int, bytes]] = []
    if pkg.npdm:
        recs.append((F.TLV_NPDM, pkg.npdm))
    if pkg.build_id:
        recs.append((F.TLV_BUILD_ID, pkg.build_id))
    if pkg.source_path:
        recs.append((F.TLV_SOURCE_PACKAGE_PATH, pkg.source_path.encode("utf-8")))
    recs.append((F.TLV_SOURCE_DUMP, dump_label.encode("utf-8")))
    if app_extra:
        # merge prebuilt application-level TLVs (names/icons/display version)
        pos = 0
        while pos + 8 <= len(app_extra):
            t, _r, size = F._tlv_s.unpack_from(app_extra, pos)
            recs.append((t, app_extra[pos + 8:pos + 8 + size]))
            pos += 8 + size
    recs.sort(key=lambda t: t[0])
    deduped: list[tuple[int, bytes]] = []
    for rec in recs:  # app_extra may repeat per-package types; keep first
        if deduped and deduped[-1][0] == rec[0]:
            continue
        deduped.append(rec)
    out = bytearray()
    for t, payload in deduped:
        out += F._tlv_s.pack(t, 0, len(payload))
        out += payload
    return bytes(out)


def _encode_localized(entries: dict[str, bytes]) -> bytes:
    """Encode {lang tag: data} as a LocalizedRecord sequence (SPEC §5.1)."""
    body = bytearray()
    seen = set()
    for lang in sorted(entries):
        try:
            tag = lang.lower().encode("ascii")
        except UnicodeEncodeError as exc:
            raise F.NupError(f"invalid language tag {lang!r}") from exc
        if (not 0 < len(tag) <= 255 or tag in seen
                or not re.fullmatch(rb"[a-z]{1,8}(?:-[a-z0-9]{1,8})*", tag)):
            raise F.NupError(f"invalid or duplicate language tag {lang!r}")
        seen.add(tag)
        data = entries[lang]
        body += bytes([len(tag)]) + tag
        body += struct.pack("<I", len(data)) + data
    return bytes(body)


def app_meta(names: dict[str | None, str] | None, icons: dict[str | None, str] | None,
             display_version: str | None, dump_label: str,
             publisher: str | None = None) -> bytes:
    """Application-level meta TLVs (SPEC §5.1): names/icons localized, plus
    display version, publisher and provenance. Attached to the base package
    (or first)."""
    names = names or {}
    icons = icons or {}
    recs: list[tuple[int, bytes]] = []
    if names.get(None):
        recs.append((F.TLV_TITLE_NAME, names[None].encode("utf-8")))
    if publisher:
        recs.append((F.TLV_PUBLISHER, publisher.encode("utf-8")))
    if names.keys() - {None}:
        localized = {lang: text.encode("utf-8")
                     for lang, text in names.items() if lang is not None}
        recs.append((F.TLV_LOCALIZED_TITLES, _encode_localized(localized)))
    if icons.get(None):
        recs.append((F.TLV_ICON, read_file(icons[None])))
    if icons.keys() - {None}:
        localized = {lang: read_file(path)
                     for lang, path in icons.items() if lang is not None}
        recs.append((F.TLV_LOCALIZED_ICONS, _encode_localized(localized)))
    if display_version:
        recs.append((F.TLV_DISPLAY_VERSION, display_version.encode("utf-8")))
    recs.append((F.TLV_SOURCE_DUMP, dump_label.encode("utf-8")))
    recs.sort(key=lambda t: t[0])  # deterministic order
    out = bytearray()
    for t, payload in recs:
        out += F._tlv_s.pack(t, 0, len(payload)) + payload
    return bytes(out)
