"""Preserve the Lumi firmware delta against the downloaded upstream archive."""
from pathlib import Path
import difflib
import zipfile
import argparse

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / ".deps/xiaozhi-source/xiaozhi-esp32-2.4.2"
parser = argparse.ArgumentParser()
parser.add_argument('--source',type=Path,default=SOURCE)
parser.add_argument('--output',default='lumi-pc-mcp.patch')
args=parser.parse_args()
SOURCE=args.source
FILES = (
    "main/application.h",
    "main/application.cc",
    "main/boards/waveshare/esp32-s3-touch-amoled-2.16/esp32-s3-touch-amoled-2.16.cc",
    "scripts/build.py",
    "main/boards/waveshare/esp32-s3-touch-amoled-2.16/lumi_notes.h",
    "main/boards/waveshare/esp32-s3-touch-amoled-2.16/config.json",
    "partitions/lumi-16m.csv",
)
patch = []
with zipfile.ZipFile(ROOT / ".deps/xiaozhi-source-v2.4.2.zip") as archive:
    for relative in FILES:
        try:
            original = archive.read("xiaozhi-esp32-2.4.2/" + relative).decode("utf-8")
        except KeyError:
            original = ""
        modified_path=SOURCE/relative
        modified=modified_path.read_text(encoding='utf-8') if modified_path.exists() else ''
        patch.extend(difflib.unified_diff(
            original.splitlines(keepends=True), modified.splitlines(keepends=True),
            fromfile="a/" + relative, tofile="b/" + relative,
        ))
        if relative.startswith("main/") and modified_path.exists():
            (Path(__file__).parent / Path(relative).name).write_text(modified, encoding="utf-8")
output = Path(__file__).parent / args.output
output.write_text("".join(patch), encoding="utf-8")
print(f"Saved {len(patch)} patch lines: {output}")
