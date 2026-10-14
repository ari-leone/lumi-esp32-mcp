"""GPT-Live adapter for XiaoZhi's half-duplex Opus transport.

The stock board pauses capture while speaking. Feed paced silence during those
gaps; this mode cannot provide GPT-Live's full-duplex voice interruption.
"""
import asyncio
import base64
import json
import time

import numpy as np

from audio_codec import OpusOutput
from server import Bridge, log, notebook_instructions


def live_session_config(cfg):
    return {
        "model": "gpt-live-1", "store": False,
        "instructions": "Habla siempre en español, breve y natural. "
            "Delega siempre al backend las peticiones de notas, tareas, volumen o estado del dispositivo. "
            "No afirmes que has cambiado el volumen hasta recibir confirmación real. " + notebook_instructions(cfg),
        "audio": {"format": {"type": "audio/pcm", "rate": 24000},
                  "output": {"voice": cfg.get("voice", "marin")}},
        "delegation": {"type": "responses", "responses": {
            "model": cfg.get("live_backend_model", "gpt-5.6-luna"),
            "instructions": "Usa las herramientas para consultar el estado y cambiar el volumen. "
                "Solo confirma acciones cuando la herramienta confirme éxito. Responde en español. " + notebook_instructions(cfg),
            "tools": [], "parallel_tool_calls": False, "max_output_tokens": 600,
        }},
    }


class LiveBridge(Bridge):
    def __init__(self, device, api, cfg):
        super().__init__(device, api, cfg)
        self.mic = bytearray()
        self.last_output = 0.0
        self.silent_samples = 0
        self.calls = {}
        self.seen_calls = set()
        self.output_lock = asyncio.Lock()
        self.last_voice_input = None
        self.listen_started = None
        self.mic_packets = 0
        self.last_mic_packet = None

    async def initialize(self):
        await self.event("session.start", session=live_session_config(self.cfg))
        async with asyncio.timeout(15):
            while True:
                msg = json.loads(await self.api.recv())
                if msg["type"] == "session.started":
                    log.info("GPT-Live preparado")
                    return
                if msg["type"] == "error":
                    raise RuntimeError("GPT-Live: " + str(msg.get("error", {}).get("code")))

    async def event(self, kind, **kwargs):
        # Reuse the existing MCP allowlist/discovery and tool validation.
        if kind == "session.update" and kwargs.get("session", {}).get("type") == "realtime":
            tools = kwargs["session"].get("tools")
            if tools is None:
                return
            kwargs = {"session": {"delegation": {"type": "responses", "responses": {
                "tools": [{**tool, "strict": False} for tool in tools]}}}}
        if kind == "conversation.item.create":
            kind = "response.item.create"
        await super().event(kind, **kwargs)

    async def device_loop(self):
        while True:
            message = await asyncio.wait_for(self.device.receive(), 180)
            if message["type"] == "websocket.disconnect":
                log.info("Placa cerró la sesión de voz (código %s)", message.get("code"))
                return
            if message.get("bytes") is not None:
                if self.listening and not self.playing:
                    pcm = self.input.decode(message["bytes"])
                    now = time.monotonic()
                    self.mic_packets += 1
                    if self.last_mic_packet is not None and now - self.last_mic_packet > 0.5:
                        log.info("Diagnóstico audio: pausa de entrada %.2f s", now - self.last_mic_packet)
                    self.last_mic_packet = now
                    if pcm:
                        samples = np.frombuffer(pcm, dtype="<i2").astype(float)
                        # Approximate activity measurement; no audio or transcripts stored.
                        if np.sqrt(np.mean(samples * samples)) >= 200:
                            self.last_voice_input = now
                    self.mic.extend(pcm)
                    if len(self.mic) > 48000:  # Fail rather than grow latency indefinitely.
                        raise RuntimeError("Cola de micrófono Live desbordada")
                continue
            msg = json.loads(message.get("text", "{}"))
            if msg.get("type") == "mcp":
                payload = msg.get("payload", {})
                future = self.pending.get(payload.get("id"))
                if future and not future.done():
                    if "error" in payload:
                        future.set_exception(RuntimeError("Error MCP"))
                    else:
                        future.set_result(payload.get("result", {}))
            elif msg.get("type") == "listen":
                self.listening = msg.get("state") == "start"
                if self.listening:
                    self.mic.clear()
                    self.listen_started = time.monotonic()
                    self.last_voice_input = None
                    self.last_mic_packet = None
                    self.mic_packets = 0
                log.info("Diagnóstico audio: micrófono %s", msg.get("state"))
            elif msg.get("type") == "abort":
                await self.stop_playback()
                await self.event("session.instructions.append", delegation_id=None,
                                 content="Deja de hablar y espera la siguiente petición del usuario.")

    async def input_loop(self):
        deadline = time.monotonic()
        size = 2880  # 60 ms PCM16 / 24 kHz; continuous and paced, even while silent.
        while True:
            chunk = bytes(self.mic[:size])
            del self.mic[:len(chunk)]
            await self.event("session.input_audio.append",
                             audio=base64.b64encode(chunk.ljust(size, b"\0")).decode())
            deadline = max(deadline + 0.06, time.monotonic())
            await asyncio.sleep(max(0, deadline - time.monotonic()))

    async def finish_output(self):
        if self.output is not None:
            for packet in self.output.finish():
                self.audio_queue.put_nowait((self.generation, packet))
            self.output = None
            self.audio_queue.put_nowait((self.generation, {"type": "tts", "state": "stop"}))
            await self.set_emotion("lumi_neutral")
        self.silent_samples = 0

    async def output_watchdog(self):
        # Live has no output-audio-done event. An idle gap is only a transport
        # heuristic, not evidence that a delegated backend task has completed.
        while True:
            await asyncio.sleep(0.1)
            async with self.output_lock:
                if self.output is not None and time.monotonic() - self.last_output > 0.8:
                    await self.finish_output()

    async def api_loop(self):
        async for raw in self.api:
            msg = json.loads(raw)
            kind = msg.get("type")
            if kind == "error":
                log.error("GPT-Live: %s", msg.get("error", {}).get("code", "unknown"))
                raise RuntimeError("Error GPT-Live")
            if kind == "session.closed":
                return
            if kind == "session.output_audio.delta":
                pcm = base64.b64decode(msg["delta"])
                if not pcm:
                    continue
                samples = np.frombuffer(pcm, dtype="<i2").astype(float)
                quiet = np.sqrt(np.mean(samples * samples)) < 40
                async with self.output_lock:
                    self.last_output = time.monotonic()
                    if self.output is None:
                        if quiet:
                            continue
                        self.output = OpusOutput()
                        now = time.monotonic()
                        if self.last_voice_input is not None:
                            log.info("Diagnóstico audio: primera voz de salida %.2f s después de la última actividad de entrada; %d paquetes recibidos",
                                     now - self.last_voice_input, self.mic_packets)
                        elif self.listen_started is not None:
                            log.info("Diagnóstico audio: primera salida %.2f s después de empezar escucha; %d paquetes recibidos, sin voz de entrada detectada",
                                     now - self.listen_started, self.mic_packets)
                        self.playing = True
                        self.mic.clear()
                        await self.set_emotion("lumi_hablando")
                        self.audio_queue.put_nowait((self.generation, {"type": "tts", "state": "start"}))
                    for packet in self.output.push(pcm):
                        self.audio_queue.put_nowait((self.generation, packet))
                    self.silent_samples = self.silent_samples + len(samples) if quiet else 0
                    if self.silent_samples >= 14400:
                        await self.finish_output()
            elif kind == "response.event":
                event = msg.get("event", {})
                key = msg.get("delegation_id")
                if event.get("type") == "response.created":
                    self.calls[key] = []
                elif event.get("type") == "response.output_item.done":
                    item = event.get("item", {})
                    if item.get("type") == "function_call" and item["call_id"] not in self.seen_calls:
                        self.seen_calls.add(item["call_id"])
                        self.calls.setdefault(key, []).append(item)
                elif event.get("type") == "response.completed":
                    calls = self.calls.pop(key, [])
                    if calls:
                        await self.execute_tools({"output": calls})
                elif event.get("type") in ("response.failed", "response.incomplete"):
                    self.calls.pop(key, None)
                    raise RuntimeError("Backend GPT-Live no completado")
        raise RuntimeError("Conexión GPT-Live cerrada")

    async def run(self, mcp, on_session_ending=None):
        tasks = [asyncio.create_task(super().run(mcp, on_session_ending)),
                 asyncio.create_task(self.input_loop()),
                 asyncio.create_task(self.output_watchdog())]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        finally:
            if on_session_ending is not None:
                on_session_ending()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            try:
                await self.event("session.close")
                async with asyncio.timeout(5):
                    while json.loads(await self.api.recv()).get("type") != "session.closed":
                        pass
            except Exception:
                log.warning("GPT-Live: cierre sin confirmación final")
