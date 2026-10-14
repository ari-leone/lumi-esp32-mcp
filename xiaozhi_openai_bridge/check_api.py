"""Check API session and optionally request a short spoken test, without the board."""
import asyncio
import base64
import json
import sys
import wave
from pathlib import Path
from urllib.parse import quote

from websockets.asyncio.client import connect
from config import settings
from server import session_config


async def main():
    cfg = settings()
    audio = bytearray()
    async with connect("wss://api.openai.com/v1/realtime?model=" + quote(cfg["model"]),
                       additional_headers={"Authorization": "Bearer " + cfg["api_key"]}, open_timeout=12) as ws:
        await ws.send(json.dumps({"type": "session.update", "session": session_config(cfg)}))
        async with asyncio.timeout(35):
            async for raw in ws:
                event = json.loads(raw)
                if event["type"] == "error":
                    print("OpenAI error:", event.get("error", {}).get("code", "unknown"))
                    return 1
                if event["type"] == "session.updated":
                    print("Sesión OpenAI configurada correctamente.")
                    if "--speak" not in sys.argv:
                        return 0
                    await ws.send(json.dumps({"type": "response.create", "response": {
                        "instructions": "Di exactamente en español: " + (
                            "Pon el volumen al cuarenta por ciento." if "--volume-command" in sys.argv
                            else "Hola, la prueba de voz funciona.")}}))
                elif event["type"] == "response.output_audio.delta":
                    audio.extend(base64.b64decode(event["delta"]))
                elif event["type"] == "response.done":
                    if not audio or event["response"].get("status") != "completed":
                        print("No se recibió audio completo.")
                        return 1
                    output = Path(__file__).resolve().parent.parent / ".build" / "openai-prueba-voz.wav"
                    if "--volume-command" in sys.argv:
                        output = output.with_name("openai-prueba-volumen.wav")
                    with wave.open(str(output), "wb") as wav:
                        wav.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
                        wav.writeframes(audio)
                    print(f"Audio recibido: {len(audio) / 48000:.2f} segundos. WAV guardado en .build.")
                    return 0
    return 1


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except Exception as error:
        # Do not print exception bodies containing request headers.
        print("No se pudo validar OpenAI:", type(error).__name__)
        raise SystemExit(1)
