from __future__ import annotations

import hashlib
import io
import json
import os
import struct
import tempfile
import unittest
from pathlib import Path

from nup import format as F
from nup.access import extract_tree
from nup.edit import edit
from nup.meta import parse_block, decode_localized
from nup.pack import pack
from nup.read import NupReader
from nup.roundtrip import read_sidecar, SIDECAR


def mutate_toc(path, callback):
    data = bytearray(path.read_bytes())
    info = F.parse_super(data[:F.HEADER_SIZE])
    toc = bytearray(data[info['toc_offset']:info['toc_offset'] + info['toc_size']])
    callback(toc, info)
    data[info['toc_offset']:info['toc_offset'] + len(toc)] = toc
    data[:F.HEADER_SIZE] = F.pack_super(F.MAGIC, info['header_size'], info['header_version'],
        info['toc_offset'], len(toc), hashlib.sha256(toc).digest(), info['blob_offset'],
        len(data), info['package_count'], info['flags'], info['uuid'])
    path.write_bytes(data)


class AdversarialTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.source = self.work / 'dump'
        (self.source / 'base/romfs').mkdir(parents=True)
        (self.source / 'base/romfs/asset.bin').write_bytes(b'adversarial data')
        self.path = self.work / 'input.nup'
        pack(str(self.path), str(self.source))

    def file_record(self, toc):
        _, packages, directories, *_ = F._toc_head_s.unpack_from(toc)
        return F._toc_head_s.size + packages * F.PKG_SIZE + directories * F.DIR_SIZE

    def test_short_toc_is_a_domain_error(self):
        data = self.path.read_bytes()
        info = F.parse_super(data[:128])
        toc = b'bad'
        self.path.write_bytes(F.pack_super(F.MAGIC, 128, 1, 128, len(toc), hashlib.sha256(toc).digest(),
            144, 144, 1, 0, info['uuid']) + toc + bytes(13))
        with self.assertRaises(F.NupError):
            NupReader(str(self.path))

    def test_child_out_of_bounds_rejected_on_open(self):
        def change(toc, _):
            _, packages, directories, files, *_ = F._toc_head_s.unpack_from(toc)
            start = 48 + packages * 64 + directories * 24 + files * 80
            struct.pack_into('<I', toc, start, directories + files + 17)
        mutate_toc(self.path, change)
        with self.assertRaises(F.NupError):
            NupReader(str(self.path))

    def test_directory_cycle_rejected_on_open(self):
        def change(toc, _):
            _, packages, directories, files, *_ = F._toc_head_s.unpack_from(toc)
            start = 48 + packages * 64 + directories * 24 + files * 80
            struct.pack_into('<I', toc, start, 0)
        mutate_toc(self.path, change)
        with self.assertRaises(F.NupError):
            NupReader(str(self.path))

    def test_nonzero_reserved_file_bytes_rejected(self):
        def change(toc, _):
            toc[self.file_record(toc) + 68] = 1
        mutate_toc(self.path, change)
        with self.assertRaises(F.NupError):
            NupReader(str(self.path))

    def test_metadata_cannot_overlap_file_extent(self):
        def change(toc, _):
            offset = struct.unpack_from('<Q', toc, self.file_record(toc) + 16)[0]
            struct.pack_into('<QI', toc, 48 + 32, offset, 8)
        mutate_toc(self.path, change)
        with self.assertRaises(F.NupError):
            NupReader(str(self.path))

    def test_extract_tree_refuses_traversal_before_writing(self):
        def change(toc, _):
            pool = F._toc_head_s.unpack_from(toc)[4]
            off = struct.unpack_from('<I', toc, self.file_record(toc))[0]
            toc[pool + off:pool + off + 9] = b'../escape'
        mutate_toc(self.path, change)
        destination = self.work / 'out'
        with NupReader(str(self.path)) as reader:
            with self.assertRaises(F.NupError):
                extract_tree(reader, str(destination), reader.packages[0].root_dir)
        self.assertFalse((destination / 'escape').exists())

    def test_extract_tree_does_not_overwrite_existing_files(self):
        destination = self.work / 'out'
        (destination / 'romfs').mkdir(parents=True)
        existing = destination / 'romfs/asset.bin'
        existing.write_bytes(b'keep original')
        with NupReader(str(self.path)) as reader:
            with self.assertRaises((F.NupError, FileExistsError)):
                extract_tree(reader, str(destination), reader.packages[0].root_dir)
        self.assertEqual(existing.read_bytes(), b'keep original')

    def test_extract_tree_refuses_preexisting_directory_symlink(self):
        destination = self.work / 'out'
        destination.mkdir()
        outside = self.work / 'outside'
        outside.mkdir()
        try:
            (destination / 'romfs').symlink_to(outside, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f'symlink unavailable: {exc}')
        from nup.sourceio import is_link
        if not os.path.lexists(destination / 'romfs') or not is_link(os.lstat(destination / 'romfs')):
            self.skipTest('host reports symlink success without creating a link (Wine)')
        with NupReader(str(self.path)) as reader:
            with self.assertRaises(F.NupError):
                extract_tree(reader, str(destination), reader.packages[0].root_dir)
        self.assertFalse((outside / 'asset.bin').exists())

    def test_edit_never_clobbers_an_unrelated_legacy_temporary_file(self):
        legacy = Path(str(self.path) + '.tmp')
        legacy.write_bytes(b'not owned by this edit')
        edit(str(self.path), publisher='Publisher')
        self.assertEqual(legacy.read_bytes(), b'not owned by this edit')

    def test_read_file_checks_content_hash(self):
        with NupReader(str(self.path)) as reader:
            offset = reader.files[0][3]
        data = bytearray(self.path.read_bytes())
        data[offset] ^= 1
        self.path.write_bytes(data)
        with NupReader(str(self.path)) as reader:
            with self.assertRaises(F.NupError):
                reader.read_file(0)

    def test_opaque_metadata_tail_is_preserved_and_reserved_fields_rejected(self):
        from nup.meta import update_block, serialize_block
        block = serialize_block({5: b"Title"}) + b"opaque"
        changed = update_block(block, {5: b"New title", 6: b"Studio"})
        self.assertTrue(changed.endswith(b"opaque"))
        self.assertEqual(parse_block(changed), {5: b"New title", 6: b"Studio"})
        with self.assertRaises(F.NupError):
            parse_block(struct.pack('<HHI', 5, 1, 1) + b'x')

    def test_case_insensitive_duplicate_localized_tags_rejected(self):
        payload = b'\x02en\x01\0\0\0A\x02EN\x01\0\0\0B'
        with self.assertRaises(F.NupError):
            decode_localized(payload)

    def test_invalid_sidecar_shapes_rejected(self):
        cases = [[], {'format': 1, 'packages': []},
                 {'format': 1, 'packages': [{'path': 'base', 'block': '', 'kind': 999}]},
                 {'format': 1, 'packages': [{'path': 'base', 'block': '', 'kind': 0,
                    'title_id': -1, 'version': 0, 'flags': 0}]}]
        for value in cases:
            with self.subTest(value=value):
                (self.source / SIDECAR).write_text(json.dumps(value), encoding='utf-8')
                with self.assertRaises(F.NupError):
                    read_sidecar(str(self.source))

    def test_packing_refuses_symlinked_source_files(self):
        outside = self.work / 'secret'
        outside.write_bytes(b'not part of dump')
        try:
            (self.source / 'base/romfs/link.bin').symlink_to(outside)
        except OSError as exc:
            self.skipTest(f'symlink unavailable: {exc}')
        from nup.sourceio import is_link
        link = self.source / 'base/romfs/link.bin'
        if not os.path.lexists(link) or not is_link(os.lstat(link)):
            self.skipTest('host reports symlink success without creating a link (Wine)')
        with self.assertRaises((F.NupError, OSError)):
            pack(str(self.work / 'with-link.nup'), str(self.source))

    def test_flat_extraction_refuses_names_containing_separators(self):
        from nup.access import extract_flat
        def change(toc, _):
            pool = F._toc_head_s.unpack_from(toc)[4]
            off = struct.unpack_from('<I', toc, self.file_record(toc))[0]
            toc[pool + off:pool + off + 9] = b'../escape'
        mutate_toc(self.path, change)
        with NupReader(str(self.path)) as reader:
            with self.assertRaises(F.NupError):
                extract_flat(reader, str(self.work / 'flat'))
        self.assertFalse((self.work / 'flat').exists())

    def test_verify_reports_corrupt_zstd_without_leaking_file_handles(self):
        from nup.verify import verify
        (self.source / 'base/romfs/asset.bin').write_bytes(b'compress me' * 10000)
        compressed = self.work / 'compressed.nup'
        pack(str(compressed), str(self.source))
        with NupReader(str(compressed)) as reader:
            self.assertEqual(reader.files[0][5], F.CODEC_ZSTD)
            offset = reader.files[0][3]
        raw = bytearray(compressed.read_bytes())
        raw[offset:offset + 4] = b'BAD!'
        compressed.write_bytes(raw)
        ok, problems = verify(str(compressed), deep=True)
        self.assertFalse(ok)
        self.assertIn('decompression', str(problems))
        compressed.unlink()  # Fails on Windows if verification leaked a mapping.

    def test_source_changes_between_hashing_and_writing_are_rejected(self):
        from unittest.mock import patch
        from nup.sourceio import open_source
        class ChangingFile:
            def __init__(self, path):
                self.stream = open_source(path)
                self.changed = None
            def __enter__(self):
                return self
            def __exit__(self, *args):
                self.stream.close()
            def fileno(self):
                return self.stream.fileno()
            def read(self, size=-1):
                return (self.changed or self.stream).read(size)
            def seek(self, *args):
                self.changed = io.BytesIO(b'x' * os.fstat(self.stream.fileno()).st_size)
                return self.changed.seek(*args)
        output = self.work / 'changed.nup'
        with patch('nup.pack.open_source', ChangingFile):
            with self.assertRaises(F.NupError):
                pack(str(output), str(self.source))
        self.assertFalse(output.exists())

    @unittest.skipUnless(hasattr(os, 'mkfifo'), 'POSIX FIFO test')
    def test_dump_discovery_refuses_special_files_without_opening_them(self):
        from nup.discover import Tree
        os.mkfifo(self.source / 'base/romfs/pipe')
        with self.assertRaises(F.NupError):
            Tree(set()).add_tree(str(self.source / 'base'))

    def test_generated_artwork_cannot_hide_arbitrary_content(self):
        package = dict(path='base', title_id=0, kind=0, version=0, flags=0, block='')
        data = dict(format=1, packages=[package], artwork=[dict(path='base/romfs/asset.bin',
            sha256=hashlib.sha256(b'adversarial data').hexdigest(), created_directory=False)])
        (self.source / SIDECAR).write_text(json.dumps(data), encoding='utf-8')
        with self.assertRaises(F.NupError):
            read_sidecar(str(self.source))

    def test_windows_device_aliases_and_utf16_length_are_rejected(self):
        from nup.access import _valid_windows_component
        for name in ('COM¹.dat', 'LPT²', 'CONIN$', 'CONOUT$', 'CON .txt', 'COM¹ .dat', '😀' * 128):
            self.assertFalse(_valid_windows_component(name))

    def test_zstd_frame_size_mismatch_rejected_before_output(self):
        import zstandard
        (self.source / 'base/romfs/asset.bin').write_bytes(b'z' * 100000)
        compressed = self.work / 'wrong-size.nup'
        pack(str(compressed), str(self.source))
        def change(toc, _):
            struct.pack_into('<Q', toc, self.file_record(toc) + 8, 1)
        mutate_toc(compressed, change)
        with NupReader(str(compressed)) as reader:
            output = io.BytesIO()
            with self.assertRaises(F.NupError):
                reader.copy_file(0, output)
            self.assertEqual(output.getvalue(), b'')

    def test_deterministic_authenticated_toc_mutations_fail_cleanly(self):
        import random
        randomizer = random.Random(20261110)
        original = self.path.read_bytes()
        info = F.parse_super(original[:128])
        accepted = rejected = 0
        for _ in range(400):
            self.path.write_bytes(original)
            def change(toc, _info):
                index = randomizer.randrange(len(toc))
                toc[index] ^= 1 << randomizer.randrange(8)
            mutate_toc(self.path, change)
            try:
                with NupReader(str(self.path)):
                    accepted += 1
            except F.NupError:
                rejected += 1
        self.assertGreater(accepted, 0)
        self.assertGreater(rejected, 0)

    def test_unpack_accepts_zstd_window_larger_than_256_kib(self):
        import zstandard
        from nup.operations import unpack_atomic

        # A frame larger than the copy buffer forces streaming decompression.
        payload = b'compress me\n' * 500000
        (self.source / 'base/romfs/asset.bin').write_bytes(payload)
        package = self.work / 'compressed.nup'
        pack(str(package), str(self.source))
        with NupReader(str(package)) as reader:
            _, _, _, offset, _, codec = reader.file_info(0)
        self.assertEqual(codec, F.CODEC_ZSTD)
        with package.open('rb') as stream:
            stream.seek(offset)
            frame = zstandard.get_frame_parameters(stream.read(18))
        self.assertGreater(frame.window_size, 256 << 10)

        output = self.work / 'unpacked'
        unpack_atomic(str(package), str(output))
        self.assertEqual((output / 'base/romfs/asset.bin').read_bytes(), payload)

    def test_large_zstd_window_is_rejected_before_decoder_allocation(self):
        import zstandard
        (self.source / 'base/romfs/asset.bin').write_bytes(b'z' * 100000)
        compressed = self.work / 'large-window.nup'
        pack(str(compressed), str(self.source))
        with NupReader(str(compressed)) as reader:
            offset = reader.files[0][3]
        forged = b'\x28\xb5\x2f\xfd\x80\x98' + struct.pack('<I', 100000)
        self.assertEqual(zstandard.get_frame_parameters(forged).window_size, 512 << 20)
        data = bytearray(compressed.read_bytes())
        data[offset:offset + len(forged)] = forged
        compressed.write_bytes(data)
        with NupReader(str(compressed)) as reader:
            output = io.BytesIO()
            with self.assertRaisesRegex(F.NupError, 'window limit'):
                reader.copy_file(0, output)
            self.assertEqual(output.getvalue(), b'')

    def test_copy_file_handles_short_writes_and_rejects_stalled_output(self):
        class Partial(io.BytesIO):
            def write(self, data):
                return super().write(data[:3])
        class Stalled:
            def write(self, data):
                return 0
        with NupReader(str(self.path)) as reader:
            output = Partial()
            reader.copy_file(0, output)
            self.assertEqual(output.getvalue(), b'adversarial data')
            with self.assertRaises(OSError):
                reader.copy_file(0, Stalled())

    def test_cli_info_does_not_emit_terminal_controls_from_metadata(self):
        from contextlib import redirect_stdout
        from nup.cli import main
        from nup.meta import serialize_block
        from test_metadata import replace_metadata
        replace_metadata(self.path, [serialize_block({4: b'1.0\x1b]52;c;payload\x07'})])
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(['info', str(self.path)]), 0)
        self.assertNotIn('\x1b', output.getvalue())
        self.assertNotIn('\x07', output.getvalue())
        self.assertIn('1.0', output.getvalue())

    def test_cli_extract_uses_numeric_package_index_and_rejects_unknown_selector(self):
        from contextlib import redirect_stdout, redirect_stderr
        from nup.cli import main
        (self.source / 'dlc/040074a01bf13001/0/romfs').mkdir(parents=True)
        (self.source / 'dlc/040074a01bf13001/0/romfs/addon.bin').write_bytes(b'addon')
        path = self.work / 'multiple.nup'
        pack(str(path), str(self.source))
        destination = self.work / 'selected'
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(main(['extract', str(path), str(destination), '--package', '1']), 0)
            self.assertEqual(main(['extract', str(path), str(self.work / 'bad'), '--package', 'invalid']), 1)
        self.assertEqual((destination / 'romfs/addon.bin').read_bytes(), b'addon')
        self.assertFalse((destination / 'romfs/asset.bin').exists())
        self.assertFalse((self.work / 'bad').exists())

    def test_windows_reparse_attributes_are_detected_even_for_regular_file_modes(self):
        import stat
        from types import SimpleNamespace
        from nup.sourceio import is_link
        self.assertTrue(is_link(SimpleNamespace(st_mode=stat.S_IFREG, st_file_attributes=0x400)))
        self.assertTrue(is_link(SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x410)))
        self.assertFalse(is_link(SimpleNamespace(st_mode=stat.S_IFREG, st_file_attributes=0x20)))
