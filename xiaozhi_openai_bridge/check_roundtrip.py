"""Real OpenAI round trip through a temporary localhost server and simulated board.

Uses the short WAV from check_api.py, not private microphone recordings.
Never changes the real board or its endpoint.
"""
import asyncio
import json
from pathlib import Path
import socket
import subprocess
import sys
import wave

import httpx
from websockets.asyncio.client import connect

from audio_codec import OpusInput, OpusOutput
from config import settings


async def main():
    cfg = settings()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    process = subprocess.Popen([sys.executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1",
                                "--port", str(port), "--no-access-log", "--log-level", "error"],
                               cwd=Path(__file__).parent, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        async with httpx.AsyncClient(trust_env=False) as client:
            for _ in range(50):
                try:
                    response = await client.get(f"http://127.0.0.1:{port}/health")
                    if response.status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(0.1)
            else:
                raise RuntimeError("Servidor local no disponible")
        audio_path = Path(__file__).resolve().parent.parent / ".build" / "openai-prueba-voz.wav"
        volume_test = "--volume-test" in sys.argv
        volume_calls = []
        if volume_test:
            audio_path = audio_path.with_name("openai-prueba-volumen.wav")
        with wave.open(str(audio_path), "rb") as wav:
            pcm = wav.readframes(wav.getnframes())
        received = bytearray()
        decoder = OpusInput()
        async with connect(f"ws://127.0.0.1:{port}/ws", additional_headers={
            "Device-Id": cfg["device_id"], "Authorization": "Bearer " + cfg["token"]}) as ws:
            await ws.send(json.dumps({"type": "hello", "version": 1, "transport": "websocket",
                                     "features": {"mcp": True}, "audio_params": {
                                         "format": "opus", "channels": 1, "sample_rate": 24000, "frame_duration": 60}}))
            hello = json.loads(await ws.recv())
            assert hello["type"] == "hello"

            async def send_audio():
                await ws.send(json.dumps({"type": "listen", "state": "start", "mode": "manual"}))
                encoder = OpusOutput()
                for packet in encoder.push(pcm) + encoder.finish():
                    await ws.send(packet)
                    await asyncio.sleep(0.06)
                await ws.send(json.dumps({"type": "listen", "state": "stop"}))

            sender = asyncio.create_task(send_audio())
            try:
                async with asyncio.timeout(45):
                    async for message in ws:
                        if isinstance(message, bytes):
                            received.extend(decoder.decode(message))
                            continue
                        event = json.loads(message)
                        if event.get("type") == "mcp":
                            payload = event["payload"]
                            if "id" not in payload:
                                continue
                            result = {"tools": [{"name": "self.audio_speaker.set_volume",
                                "description": "Set volume", "inputSchema": {"type": "object",
                                    "properties": {"volume": {"type": "integer", "minimum": 0, "maximum": 100}},
                                    "required": ["volume"]}}]} if payload["method"] == "tools/list" else {
                                        "protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                                        "serverInfo": {"name": "simulated-device", "version": "test"}}
                            if payload["method"] == "tools/call":
                                assert payload["params"]["name"] == "self.audio_speaker.set_volume"
                                assert payload["params"]["arguments"] == {"volume": 40}
                                volume_calls.append(payload["params"])
                                result = {"isError": False, "content": [{"type": "text", "text": '{"volume":40,"success":true}'}]}
                            await ws.send(json.dumps({"type": "mcp", "payload": {
                                "jsonrpc": "2.0", "id": payload["id"], "result": result}}))
                        elif event.get("type") == "alert":
                            raise RuntimeError("El servidor indicó un error")
                        elif event.get("type") == "tts" and event.get("state") == "stop":
                            if not volume_test or volume_calls:
                                break
                await sender
            finally:
                sender.cancel()
                await asyncio.gather(sender, return_exceptions=True)
        if len(received) < 4800:
            raise RuntimeError("No se recibió respuesta de voz")
        if volume_test and len(volume_calls) != 1:
            raise RuntimeError("No se verificó una única acción MCP de volumen")
        output = audio_path.with_name("openai-puente-respuesta.wav")
        with wave.open(str(output), "wb") as wav:
            wav.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
            wav.writeframes(received)
        print(f"Prueba completa con placa simulada: {len(received) / 48000:.2f} s de respuesta Opus recibidos.")
        if volume_test:
            print("MCP simulado: petición hablada ejecutó volumen=40 una sola vez.")
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as error:
        print("Prueba no completada:", type(error).__name__)
        raise SystemExit(1)
