"""Capture diagnostic serial logs, omitting conversation text and URLs."""
import argparse
from pathlib import Path
import re
import time
import serial

parser = argparse.ArgumentParser()
parser.add_argument("--port", default="COM3")
parser.add_argument("--seconds", type=float, default=45)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--reset", action="store_true")
args = parser.parse_args()
args.output.parent.mkdir(parents=True, exist_ok=True)
port = serial.Serial(port=None, baudrate=115200, timeout=0.2)
port.dtr = False
port.rts = False
port.port = args.port
deadline = time.monotonic() + 10
while True:
    try:
        port.open()
        break
    except serial.SerialException:
        if time.monotonic() >= deadline:
            raise
        time.sleep(0.25)
if args.reset:
    from esptool.reset import HardReset
    HardReset(port, uses_usb=True).reset()
    port.close()
    deadline = time.monotonic() + 10
    while True:
        try:
            port.open()
            break
        except serial.SerialException:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.25)
count = 0
pending = b""
with port, args.output.open("w", encoding="utf-8") as output:
    end = time.monotonic() + args.seconds
    while time.monotonic() < end:
        pending += port.read(port.in_waiting or 1)
        while b"\n" in pending:
            raw, pending = pending.split(b"\n", 1)
            line = raw.decode("utf-8", errors="replace").strip()
            if any(marker in line for marker in ("<<", ">>", "Received custom message")):
                continue
            line = re.sub(r"(?:https?|wss?)://\S+", "[URL omitida]", line)
            line = re.sub(r"(?i)(token|api[_-]?key|authorization)(\s*[:=]\s*)\S+",
                          r"\1\2[omitido]", line)
            if line:
                output.write(line[:1000] + "\n")
                output.flush()
                count += 1
print(f"Guardadas {count} líneas de diagnóstico en {args.output}")
