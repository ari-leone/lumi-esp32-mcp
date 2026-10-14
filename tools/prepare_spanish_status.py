"""Translate fixed UI strings in the verified 2.4.2 image without moving code.

Offline preparation only. A current board backup and comparison are required
before writing. Original image and rollback file are retained under .build.
"""
import functools
import hashlib
import json
import operator
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / '.build'
SOURCE = BUILD / 'application-original-2.4.2.bin'
TARGET = BUILD / 'application-estados-es-2.4.2.bin'
TRANSLATIONS = {
    '待命': 'Pausa',
    '聆听中...': 'Escuchando',
    '说话中...': 'Respondiendo',
    '连接中...': 'Conectando',
    '初始化...': 'Iniciando',
    '检查新版本...': 'Comprobando...',
    '错误': 'Error',
}


def layout(image):
    assert image[0] == 0xe9, 'Invalid ESP image header'
    position = 24
    segments = []
    for _ in range(image[1]):
        _, size = struct.unpack_from('<II', image, position)
        position += 8
        assert size > 0 and position + size <= len(image)
        segments.append((position, size))
        position += size
    checksum_end = (position // 16 + 1) * 16
    assert image[23] == 1, 'Expected appended SHA256'
    assert len(image) == checksum_end + 32
    return segments, checksum_end


def image_checksum(image, segments):
    value = 0xef
    for start, size in segments:
        value = functools.reduce(operator.xor, image[start:start+size], value)
    return value


def main():
    original = SOURCE.read_bytes()
    segments, checksum_end = layout(original)
    assert image_checksum(original, segments) == original[checksum_end-1]
    assert hashlib.sha256(original[:checksum_end]).digest() == original[checksum_end:]
    patched = bytearray(original)
    changes = []
    for old, new in TRANSLATIONS.items():
        needle = old.encode() + b'\0'
        replacement = new.encode()
        assert len(replacement) <= len(needle)-1, 'Translation would move existing code'
        assert original.count(needle) == 1, 'String is missing or ambiguous'
        pos = original.index(needle)
        assert any(start <= pos and pos+len(needle) <= start+size for start,size in segments)
        patched[pos:pos+len(needle)] = replacement.ljust(len(needle), b'\0')
        changes.append({'original': old, 'spanish': new, 'image_offset': hex(pos)})
    patched[checksum_end-1] = image_checksum(patched, segments)
    patched[checksum_end:] = hashlib.sha256(patched[:checksum_end]).digest()
    assert len(patched) == len(original)
    assert image_checksum(patched, segments) == patched[checksum_end-1]
    assert hashlib.sha256(patched[:checksum_end]).digest() == patched[checksum_end:]
    changed_sectors = sorted({i // 4096 * 4096 for i,(a,b) in enumerate(zip(original,patched)) if a != b})
    TARGET.write_bytes(patched)
    report = {'source_sha256': hashlib.sha256(original).hexdigest(),
              'target_sha256': hashlib.sha256(patched).hexdigest(),
              'changes': changes, 'image_bytes': len(patched),
              'changed_flash_sectors': [hex(0x20000+s) for s in changed_sectors],
              'requires_current_backup_comparison': True}
    TARGET.with_suffix('.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Verified ESP checksum and SHA256 before and after translation.')
    print('Translated states:', ', '.join(TRANSLATIONS.values()))
    print('Changed sectors:', ', '.join(report['changed_flash_sectors']))


if __name__ == '__main__':
    main()
