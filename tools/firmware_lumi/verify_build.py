"""Verify and preserve an application-only Lumi touch build before flashing."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from prepare_spanish_status import layout, image_checksum

parser = argparse.ArgumentParser()
parser.add_argument("build", type=Path)
args = parser.parse_args()
root = Path(__file__).resolve().parents[2]
ota_data = (root / ".build/otadata-antes-tactil-20261004.bin").read_bytes()
valid_entries = []
for offset in (0, 4096):
    sequence = struct.unpack_from("<I", ota_data, offset)[0]
    state, checksum = struct.unpack_from("<II", ota_data, offset + 24)
    if sequence != 0xFFFFFFFF and state not in (3, 4):
        assert zlib.crc32(ota_data[offset:offset + 4], 0xFFFFFFFF) == checksum
        valid_entries.append(sequence)
assert valid_entries and (max(valid_entries) - 1) % 2 == 0, "Active partition is not ota_0"
image = (args.build / "xiaozhi.bin").read_bytes()
assert len(image) <= 0x3F0000, "Application exceeds the installed OTA partition"
assert struct.unpack_from("<H", image, 12)[0] == 9, "Expected ESP32-S3 image"
segments, end = layout(image)
assert image_checksum(image, segments) == image[end - 1], "Invalid ESP checksum"
assert hashlib.sha256(image[:end]).digest() == image[end:], "Invalid appended SHA256"
for marker in (b"Lumi touch: start chat", b"Lumi touch: stop chat", b"es-ES"):
    assert marker in image, f"Missing required build marker: {marker!r}"
configuration = (args.build.parent / "sdkconfig").read_text(encoding="utf-8")
for setting in (
    "CONFIG_BOARD_TYPE_WAVESHARE_ESP32_S3_TOUCH_AMOLED_2_16=y",
    "CONFIG_LANGUAGE_ES_ES=y", "CONFIG_SPIRAM_MODE_OCT=y",
    "CONFIG_ESPTOOLPY_FLASHSIZE_16MB=y",
):
    assert setting in configuration, f"Incorrect configuration: {setting}"
target = root / ".build/application-lumi-tactil-es-2.4.2.bin"
target.write_bytes(image)
metadata = {
    "sha256": hashlib.sha256(image).hexdigest(), "bytes": len(image),
    "flash_offset": "0x20000", "partition_bytes": 0x3F0000,
    "board": "esp32-s3-touch-amoled-2.16", "language": "es-ES",
    "sdk": "ESP-IDF 6.0.2", "application_only": True,
    "backup": ".build/respaldo-app-antes-tactil-20261004.bin",
    "installed": False,
}
target.with_suffix(".json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
print(json.dumps(metadata, indent=2))
