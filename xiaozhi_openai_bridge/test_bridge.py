import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi.testclient import TestClient

import server
from audio_codec import OpusInput, OpusOutput

CFG = {"api_key": "test", "model": "test", "voice": "marin", "token": "local-secret",
       "pc_ip": "192.0.2.10", "port": 8002, "device_id": "02:00:00:00:00:01"}


@pytest.mark.parametrize("utc,offset", [
    ("2026-01-15T12:00:00+00:00", 60),
    ("2026-07-15T12:00:00+00:00", 120),
    ("2026-10-25T00:59:00+00:00", 120),
    ("2026-10-25T01:01:00+00:00", 60),
])
def test_board_clock_uses_madrid_offset_without_shifting_utc_epoch(utc, offset):
    timestamp = datetime.fromisoformat(utc).timestamp()
    result = server.madrid_server_time(timestamp)
    assert result == {"timestamp": int(timestamp * 1000), "timezone_offset": offset}


def test_opus_roundtrip_keeps_frequency_and_level():
    samples = np.sin(np.arange(24000) * (2 * np.pi * 440 / 24000)) * 6000
    pcm = samples.astype("<i2").tobytes()
    encoder = OpusOutput()
    packets = encoder.push(pcm[:4000]) + encoder.push(pcm[4000:]) + encoder.finish()
    decoder = OpusInput()
    decoded = np.frombuffer(b"".join(decoder.decode(p) for p in packets), dtype="<i2")
    assert 24000 <= len(decoded) <= 27000
    assert 2500 < np.sqrt(np.mean(decoded.astype(float)**2)) < 5500
    spectrum = np.abs(np.fft.rfft(decoded[3000:20000]))
    peak = np.fft.rfftfreq(17000, 1 / 24000)[spectrum.argmax()]
    assert abs(peak - 440) < 3


def test_ota_requires_secret_and_device(monkeypatch):
    monkeypatch.setattr(server, "settings", lambda: CFG)
    client = TestClient(server.app)
    assert client.post("/ota/wrong", headers={"device-id": CFG["device_id"]}).status_code == 403
    assert client.post("/ota/local-secret").status_code == 403
    result = client.post("/ota/local-secret", headers={"device-id": CFG["device_id"]}).json()
    assert result["websocket"]["version"] == 1
    assert "firmware" not in result


def test_notebook_route_requires_auth_and_only_forwards_note_tools(monkeypatch):
    calls = []

    class NotebookDevice:
        tools = {name.replace(".", "_"): {} for name in server.NOTE_TOOLS}

        async def rpc(self, method, params):
            calls.append((method, params))
            return {"content": [{"type": "text", "text": '{"id":1}'}], "isError": False}

    monkeypatch.setattr(server, "settings", lambda: CFG)
    monkeypatch.setattr(server, "active", {CFG["device_id"]: {"bridge": NotebookDevice()}})
    client = TestClient(server.app)
    payload = {"name": "self.notes.create", "arguments": {"text": "Comprar pan"}}
    assert client.post("/notebook/tool", json=payload).status_code == 403
    headers = {"authorization": "Bearer " + CFG["token"]}
    assert client.post("/notebook/tool", headers=headers, json={"name": "self.reboot"}).status_code == 400
    assert not calls
    assert client.post("/notebook/tool", headers=headers, json=payload).json()["isError"] is False
    assert calls == [("tools/call", payload)]
    assert client.post("/notebook/tool", headers=headers, content=b"x" * 4097).status_code == 413
    server.active.clear()
    assert client.post("/notebook/tool", headers=headers, json=payload).status_code == 409


@pytest.mark.asyncio
async def test_local_notebook_session_discards_audio_and_preserves_device_errors():
    from notebook_diagnostics import NotebookDiagnostics
    device = Device()
    bridge = NotebookDiagnostics(device, None, CFG)
    success = asyncio.get_running_loop().create_future()
    rejected = asyncio.get_running_loop().create_future()
    bridge.pending = {1: success, 2: rejected}
    reader = asyncio.create_task(bridge.device_loop())
    await device.incoming.put({"type": "websocket.receive", "bytes": b"invalid-opus-not-decoded"})
    for payload in ({"id": 1, "result": {"notes": []}},
                    {"id": 2, "error": {"message": "Nota no válida"}}):
        await device.incoming.put({"type": "websocket.receive", "text": json.dumps({"type": "mcp", "payload": payload})})
    assert await asyncio.wait_for(success, 1) == {"notes": []}
    with pytest.raises(RuntimeError, match="Nota no válida"):
        await asyncio.wait_for(rejected, 1)
    await device.incoming.put({"type": "websocket.disconnect"})
    await asyncio.wait_for(reader, 1)


class Device:
    def __init__(self):
        self.incoming = asyncio.Queue()
        self.sent = []

    async def receive(self):
        return await self.incoming.get()

    async def send_json(self, msg):
        self.sent.append(msg)
        payload = msg.get("payload", {})
        if "id" in payload:
            method = payload["method"]
            result = {"tools": [{"name": name, "inputSchema": {"type": "object", "properties": {}}}
                       for name in ["self.audio_speaker.set_volume", "self.reboot"]]} if method == "tools/list" else {"isError": False}
            await self.incoming.put({"type": "websocket.receive", "text": json.dumps({"type": "mcp", "payload": {"id": payload["id"], "result": result}})})

    async def send_bytes(self, payload):
        self.sent.append(payload)


class API:
    def __init__(self):
        self.sent = []

    async def send(self, raw):
        self.sent.append(json.loads(raw))


@pytest.mark.asyncio
async def test_reconnect_during_api_cleanup_preserves_new_device_ownership(monkeypatch):
    class Socket(Device):
        def __init__(self):
            super().__init__()
            self.headers = {"device-id": CFG["device_id"],
                            "authorization": "Bearer " + CFG["token"]}
            self.accepted = asyncio.Event()
            self.finished = asyncio.Event()
            self.closed = []

        async def accept(self):
            self.accepted.set()

        async def receive_json(self):
            return {"type": "hello", "version": 1,
                    "audio_params": {"format": "opus", "channels": 1}}

        async def close(self, code=1000):
            self.closed.append(code)

    class SlowCleanup:
        def __init__(self):
            self.closing = asyncio.Event()
            self.finish_close = asyncio.Event()

        async def __aenter__(self):
            return API()

        async def __aexit__(self, *args):
            self.closing.set()
            await self.finish_close.wait()

    class SessionBridge(server.Bridge):
        async def device_loop(self):
            await self.device.finished.wait()

        async def api_loop(self):
            await asyncio.Future()

        async def playback_loop(self):
            await asyncio.Future()

    first, second, duplicate = Socket(), Socket(), Socket()
    contexts = [SlowCleanup(), SlowCleanup()]
    pending_contexts = iter(contexts)
    monkeypatch.setattr(server, "settings", lambda: CFG)
    monkeypatch.setattr(server, "connect", lambda *args, **kwargs: next(pending_contexts))
    monkeypatch.setattr(server, "Bridge", SessionBridge)
    server.active.clear()
    tasks = []
    try:
        tasks.append(asyncio.create_task(server.voice(first)))
        await asyncio.wait_for(first.accepted.wait(), 1)
        first.finished.set()
        await asyncio.wait_for(contexts[0].closing.wait(), 1)
        assert CFG["device_id"] not in server.active

        tasks.append(asyncio.create_task(server.voice(second)))
        await asyncio.wait_for(second.accepted.wait(), 1)
        newer_owner = server.active[CFG["device_id"]]
        contexts[0].finish_close.set()
        await asyncio.wait_for(tasks[0], 1)
        assert server.active[CFG["device_id"]] is newer_owner
        await server.voice(duplicate)
        assert duplicate.closed == [1013]
        assert not duplicate.accepted.is_set()

        second.finished.set()
        contexts[1].finish_close.set()
        await asyncio.wait_for(tasks[1], 1)
        assert not server.active
    finally:
        for context in contexts:
            context.finish_close.set()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        server.active.clear()


@pytest.mark.asyncio
async def test_mcp_discovery_and_real_rpc_volume():
    device, api = Device(), API()
    bridge = server.Bridge(device, api, CFG)
    reader = asyncio.create_task(bridge.device_loop())
    try:
        await bridge.discover()
        assert set(bridge.tools) == {"self_audio_speaker_set_volume"}
        await bridge.execute_tools({"output": [{"type": "function_call", "name": "self_audio_speaker_set_volume",
                                  "arguments": '{"volume":40}', "call_id": "call1"}]})
        calls = [msg["payload"] for msg in device.sent if msg.get("payload", {}).get("method") == "tools/call"]
        assert calls[0]["params"] == {"name": "self.audio_speaker.set_volume", "arguments": {"volume": 40}}
        assert api.sent[-1]["type"] == "response.create"
    finally:
        reader.cancel()
        await asyncio.gather(reader, return_exceptions=True)


@pytest.mark.asyncio
async def test_manual_short_capture_not_committed():
    device, api = Device(), API()
    bridge = server.Bridge(device, api, CFG)
    for msg in [{"type": "listen", "state": "start", "mode": "manual"}, {"type": "listen", "state": "stop"}]:
        await device.incoming.put({"type": "websocket.receive", "text": json.dumps(msg)})
    await device.incoming.put({"type": "websocket.disconnect"})
    await bridge.device_loop()
    assert not any(event["type"] == "input_audio_buffer.commit" for event in api.sent)


@pytest.mark.asyncio
async def test_abort_discards_queued_audio():
    bridge = server.Bridge(Device(), API(), CFG)
    bridge.playing = True
    bridge.audio_queue.put_nowait((0, b"obsolete"))
    await bridge.stop_playback()
    assert bridge.audio_queue.empty()
    assert not bridge.playing
    assert bridge.device.sent[-1]["state"] == "stop"


@pytest.mark.asyncio
async def test_lumi_emotions_follow_playback(monkeypatch):
    device, api = Device(), API()
    cfg = {**CFG, "lumi_emotions": True}
    bridge = server.Bridge(device, api, cfg)
    await bridge.set_emotion("lumi_hablando")
    await bridge.set_emotion("lumi_neutral")
    assert [message["emotion"] for message in device.sent] == ["lumi_hablando", "lumi_neutral"]


@pytest.mark.asyncio
async def test_playback_send_overhead_does_not_starve_audio(monkeypatch):
    clock = [100.0]
    sent_at = []
    stopped_at = []
    started_at = []

    class SlowDevice(Device):
        async def send_bytes(self, payload):
            sent_at.append(clock[0])
            clock[0] += 0.012  # Nonzero transport work must not extend each frame.

        async def send_json(self, msg):
            if msg.get("state") == "start":
                started_at.append(clock[0])
            if msg.get("state") == "stop":
                stopped_at.append(clock[0])
                raise asyncio.CancelledError

    async def sleep(delay):
        clock[0] += delay

    bridge = server.Bridge(SlowDevice(), API(), CFG)
    monkeypatch.setattr(server, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    monkeypatch.setattr(server.asyncio, "sleep", sleep)
    bridge.audio_queue.put_nowait((0, {"type": "tts", "state": "start"}))
    for _ in range(50):
        bridge.audio_queue.put_nowait((0, b"audio"))
    bridge.audio_queue.put_nowait((0, {"type": "tts", "state": "stop"}))
    with pytest.raises(asyncio.CancelledError):
        await bridge.playback_loop()
    # Every packet arrives by its playback deadline, including a three-second
    # utterance where relative sleeps would accumulate 600 ms of drift.
    assert all(t <= sent_at[0] + i * 0.06 + 0.001 for i, t in enumerate(sent_at))
    assert stopped_at[0] - sent_at[0] == pytest.approx(3.0)
    # Firmware handles START asynchronously and resets its decoder. Sending
    # audio in the same burst can erase the beginning of the utterance.
    assert sent_at[0] - started_at[0] >= 0.179
