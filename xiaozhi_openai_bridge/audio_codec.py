"""Raw Opus packets <-> mono PCM16 24 kHz. No WAV/Ogg headers on the wire."""
import struct
from fractions import Fraction

import av
import numpy as np


class OpusInput:
    def __init__(self):
        self.decoder = av.CodecContext.create("opus", "r")
        self.decoder.extradata = b"OpusHead" + struct.pack("<BBHIhB", 1, 1, 0, 48000, 0, 0)
        self.resampler = av.AudioResampler(format="s16", layout="mono", rate=24000)

    def decode(self, packet: bytes) -> bytes:
        if not packet or len(packet) > 8192:
            raise ValueError("Paquete Opus inválido")
        chunks = []
        for frame in self.decoder.decode(av.Packet(packet)):
            for converted in self.resampler.resample(frame):
                chunks.append(converted.to_ndarray().astype("<i2").tobytes())
        return b"".join(chunks)


class OpusOutput:
    FRAME_SAMPLES = 1440  # 60 ms at 24 kHz, as advertised in server hello

    def __init__(self):
        self.encoder = av.CodecContext.create("libopus", "w")
        self.encoder.sample_rate = 24000
        self.encoder.layout = "mono"
        self.encoder.format = "s16"
        self.encoder.bit_rate = 24000
        self.encoder.options = {"frame_duration": "60", "application": "voip"}
        self.encoder.open()
        self.pending = bytearray()
        self.pts = 0

    def push(self, pcm: bytes) -> list[bytes]:
        if len(pcm) % 2:
            raise ValueError("PCM incompleto")
        self.pending.extend(pcm)
        packets = []
        size = self.FRAME_SAMPLES * 2
        while len(self.pending) >= size:
            samples = np.frombuffer(bytes(self.pending[:size]), dtype="<i2").reshape(1, -1)
            del self.pending[:size]
            frame = av.AudioFrame.from_ndarray(samples, format="s16", layout="mono")
            frame.sample_rate = 24000
            frame.time_base = Fraction(1, 24000)
            frame.pts = self.pts
            self.pts += self.FRAME_SAMPLES
            packets.extend(bytes(packet) for packet in self.encoder.encode(frame))
        return packets

    def finish(self) -> list[bytes]:
        packets = []
        if self.pending:
            packets.extend(self.push(bytes(self.FRAME_SAMPLES * 2 - len(self.pending))))
        packets.extend(bytes(packet) for packet in self.encoder.encode(None))
        return packets
