"""Opt-in NUP interoperability checks using supplied consumer source checkouts.

Run with a Python containing Pillow, zstandard, capstone and lz4. BananaNative
also needs compression.zstd (Python 3.14+) or backports.zstd. No source is fetched
or changed. C/C++ filesystem/logging adapters isolate the real consumer readers;
these checks do not boot a game or build an Android application.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from nup.application import copy_application, load_application
from nup.edit import edit
from nup.pack import pack
from nup.read import NupReader
from nup.access import extract_dump
from PIL import Image

HERE = Path(__file__).resolve().parent
HARNESS = HERE / 'tests/consumer_harness'


def run(args, **options):
    result = subprocess.run([str(arg) for arg in args], capture_output=True, text=True, timeout=180, **options)
    if result.returncode:
        raise RuntimeError(f"Consumer check failed: {args[0]}\n{result.stdout}\n{result.stderr}")
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--banana-root', type=Path, required=True)
    parser.add_argument('--fritchii-root', type=Path, required=True)
    parser.add_argument('--baseline-root', type=Path, help='Optional pre-audit tools/nup directory for byte comparisons')
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    banana, fritchii = args.banana_root.resolve(), args.fritchii_root.resolve()
    result = {'banana_commit': run(['git', '-C', banana, 'rev-parse', 'HEAD']).strip(),
              'fritchii_commit': run(['git', '-C', fritchii, 'rev-parse', 'HEAD']).strip(),
              'checks': [], 'upstream_tests': {}, 'baseline_bytes_identical': {}}
    with tempfile.TemporaryDirectory(prefix='nup-consumer-check-') as temporary:
        work = Path(temporary)
        source = work / 'Game'
        run([sys.executable, '-c',
             'import sys;from pathlib import Path;sys.path.insert(0,sys.argv[1]);import test_nup;test_nup.dump(Path(sys.argv[2]))',
             banana / 'dm/tools/tests', source])
        (source / 'base/romfs/raw.bin').write_bytes(b'raw data')
        icon = work / 'icon.png'
        Image.new('RGB', (256, 256), 'blue').save(icon)
        packed = work / 'packed.nup'
        pack(str(packed), str(source), names={None: 'Compatibility title'}, publisher='Compatibility studio',
             display_version='1.2.3', icons={None: str(icon)})
        cases = [packed]
        edited = work / 'edited.nup'
        shutil.copyfile(packed, edited)
        edit(str(edited), publisher='Edited publisher')
        cases.append(edited)
        if args.baseline_root:
            baseline = work / 'baseline.nup'
            environment = {**os.environ, 'PYTHONPATH': str(args.baseline_root.resolve())}
            run([sys.executable, '-c',
                 "import sys;from nup.pack import pack;pack(sys.argv[2],sys.argv[1],names={None:'Compatibility title'},publisher='Compatibility studio',display_version='1.2.3',icons={None:sys.argv[3]})",
                 source, baseline, icon], env=environment)
            assert baseline.read_bytes() == packed.read_bytes(), 'valid packing bytes changed'
            result['baseline_bytes_identical']['packed'] = True
            run([sys.executable, '-c', 'import sys;from nup.edit import edit;edit(sys.argv[1],publisher="Edited publisher")', baseline], env=environment)
            assert baseline.read_bytes() == edited.read_bytes(), 'ordinary metadata edit bytes changed'
            result['baseline_bytes_identical']['edited'] = True
        spec = importlib.util.spec_from_file_location('audit_fixtures', HERE / 'tests/test_metadata.py')
        fixtures = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fixtures)
        transferred = work / 'transferred.nup'
        donor = work / 'donor.nup'
        shutil.copyfile(packed, transferred)
        shutil.copyfile(packed, donor)
        from nup.meta import serialize_block, _encode_localized
        nacp = bytearray(0x4000)
        nacp[:17] = b'Transferred title'
        nacp[0x200:0x212] = b'Transferred studio'
        fixtures.replace_metadata(donor, [serialize_block({2: bytes(nacp), 10: _encode_localized({'en-us': icon.read_bytes()})}),
                                         serialize_block({8: b'update'}), serialize_block({8: b'addon'})])
        copy_application(str(donor), str(transferred))
        cases.append(transferred)
        relocated = work / 'relocated.nup'
        shutil.copyfile(packed, relocated)
        fixtures.relayout_package(relocated, metadata_first=True, header_padding=64)
        edit(str(relocated), publisher='Relocated publisher')
        cases.append(relocated)
        restored = work / 'restored'
        with NupReader(str(relocated)) as reader:
            extract_dump(reader, str(restored))
        repacked = work / 'repacked.nup'
        pack(str(repacked), str(restored))
        cases.append(repacked)
        # A separate native-only case proves valid virtual names are still
        # packable even when Windows cannot materialize them as host filenames.
        label = source / 'base/romfs/literal:label.bin'
        label.write_bytes(b'valid virtual filename')
        native_labels = work / 'native-labels.nup'
        pack(str(native_labels), str(source), names={None: 'Compatibility title'}, publisher='Compatibility studio',
             display_version='1.2.3', icons={None: str(icon)})
        cases.append(native_labels)
        if args.baseline_root:
            baseline = work / 'baseline-labels.nup'
            run([sys.executable, '-c',
                 "import sys;from nup.pack import pack;pack(sys.argv[2],sys.argv[1],names={None:'Compatibility title'},publisher='Compatibility studio',display_version='1.2.3',icons={None:sys.argv[3]})",
                 source, baseline, icon], env=environment)
            assert baseline.read_bytes() == native_labels.read_bytes(), 'native label packing bytes changed'
            result['baseline_bytes_identical']['native_labels'] = True
        label.unlink()
        special_selectors = {}
        for name, relative, selector in (
                ('standalone-update', 'updates/458752', 'update/458752'),
                ('standalone-dlc', 'dlc/040074a01bf13001/0', 'addon/040074a01bf13001')):
            standalone_source = work / (name + '-dump')
            shutil.copytree(source / relative, standalone_source / relative)
            standalone = work / (name + '.nup')
            pack(str(standalone), str(standalone_source), names={None: 'Standalone title'},
                 publisher='Standalone studio', icons={None: str(icon)})
            cases.append(standalone)
            special_selectors[standalone] = [(selector, relative)]
        frit = fritchii / 'src'
        cpp = work / 'fritchii-check'
        run(['g++', '-std=c++20', '-O1', '-I' + str(HARNESS / 'stubs'), '-I' + str(frit),
             HARNESS / 'fritchii_check.cpp', frit / 'core/file_sys/nup_container.cpp',
             *[frit / ('core/file_sys/vfs/' + name + '.cpp') for name in ('vfs', 'vfs_offset', 'vfs_vector')],
             '-lzstd', '-lcrypto', '-pthread', '-o', cpp])
        native_headers = work / 'banana-native'
        (native_headers / 'plat').mkdir(parents=True)
        for name in ('nup_image.h', 'romfs_image.h'):
            shutil.copyfile(banana / 'dm/host' / name, native_headers / name)
            assert (native_headers / name).read_bytes() == (banana / 'dm/host' / name).read_bytes()
        shutil.copyfile(HARNESS / 'banana_platform.h', native_headers / 'plat/plat.h')
        native = work / 'banana-native-check'
        run(['gcc', '-std=gnu11', '-O1', '-I' + str(native_headers), HARNESS / 'banana_native.c',
             '-lzstd', '-lcrypto', '-pthread', '-o', native])
        java_src = banana / 'android/app/src/main/java/dev/nxnative/android'
        classes = work / 'java'
        run(['javac', '-d', classes,
             *[java_src / (name + '.java') for name in ('Nup', 'Zstd', 'Pack', 'DumpLayout', 'BuildCheck',
                                                       'RomfsCheck', 'Profile', 'ShaderLibs', 'PickedPath', 'CopyPlan')],
             HARNESS / 'BuildConfig.java', HARNESS / 'BananaCheck.java'])
        for case in cases:
            metadata = load_application(case)
            cpp_output = run([cpp, case, metadata.title, metadata.publisher])
            java_output = run(['java', '-cp', classes, 'dev.nxnative.android.BananaCheck', case, metadata.title, metadata.publisher])
            selectors = special_selectors.get(case, [('base', 'base'), ('update/458752', 'updates/458752'),
                                     ('addon/040074a01bf13001', 'dlc/040074a01bf13001/0')])
            for selector, folder in selectors:
                native_output = run([native, str(case) + ':' + selector])
                actual = dict(line.split('\t')[1:] for line in native_output.splitlines() if line.startswith('FILE\t'))
                root = source / folder / 'romfs'
                expected = {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                            for path in root.rglob('*') if path.is_file()}
                if case == native_labels and selector == 'base':
                    expected['literal:label.bin'] = hashlib.sha256(b'valid virtual filename').hexdigest()
                assert actual == expected, (case.name, selector, 'native RomFS content differs')
            result['checks'].append({'fixture': case.name, 'fritchii': cpp_output.strip(), 'banana_java': java_output.strip(),
                                     'banana_native_romfs_selectors': len(selectors)})
        for mode in ('packed', 'edited'):
            completed = subprocess.run([sys.executable, str(HARNESS / 'banana_tests.py'), str(banana),
                str(HARNESS / 'produce.py'), str(HERE), mode], capture_output=True, text=True, timeout=180)
            assert completed.returncode == 0, completed.stdout + completed.stderr
            result['upstream_tests'][mode] = completed.stderr
    args.report.write_text(json.dumps(result, indent=2) + '\n')
    print(f'Consumer compatibility checks passed: {len(result["checks"])} fixtures, both consumers; ' + str(args.report))


if __name__ == '__main__':
    main()
