import asyncio
import base64
import json

import pytest

from live_bridge import LiveBridge
from test_bridge import API, CFG, Device


@pytest.mark.asyncio
async def test_live_tool_result_uses_output_items_not_empty_completed_output():
    class Stream(API):
        def __aiter__(self):
            async def events():
                for event in [
                    {"type": "response.created", "response": {"id": "r1"}},
                    {"type": "response.output_item.done", "item": {
                        "type": "function_call", "call_id": "c1",
                        "name": "self_audio_speaker_set_volume", "arguments": '{"volume":40}'}},
                    {"type": "response.completed", "response": {"id": "r1", "output": []}},
                ]:
                    yield json.dumps({"type": "response.event", "delegation_id": "d1", "event": event})
                yield json.dumps({"type": "session.closed"})
            return events()

    device, api = Device(), Stream()
    bridge = LiveBridge(device, api, CFG)
    bridge.tools = {"self_audio_speaker_set_volume": {"name": "self.audio_speaker.set_volume"}}
    reader = asyncio.create_task(bridge.device_loop())
    try:
        await bridge.api_loop()
    finally:
        reader.cancel()
        await asyncio.gather(reader, return_exceptions=True)
    assert api.sent[0]["type"] == "response.item.create"
    assert api.sent[0]["item"]["call_id"] == "c1"
    assert api.sent[1]["type"] == "response.create"
    assert device.sent[0]["payload"]["params"]["arguments"] == {"volume": 40}


@pytest.mark.asyncio
async def test_live_continues_silence_when_board_is_not_capturing():
    class Once(API):
        async def send(self, raw):
            await super().send(raw)
            raise asyncio.CancelledError

    api = Once()
    bridge = LiveBridge(Device(), api, CFG)
    with pytest.raises(asyncio.CancelledError):
        await bridge.input_loop()
    assert api.sent[0]["type"] == "session.input_audio.append"
    assert base64.b64decode(api.sent[0]["audio"]) == bytes(2880)


@pytest.mark.asyncio
async def test_live_discovery_maps_tools_to_responses():
    device, api = Device(), API()
    bridge = LiveBridge(device, api, CFG)
    reader = asyncio.create_task(bridge.device_loop())
    try:
        await bridge.discover()
    finally:
        reader.cancel()
        await asyncio.gather(reader, return_exceptions=True)
    session = api.sent[-1]["session"]
    assert "type" not in session
    assert session["delegation"]["responses"]["tools"][0]["name"] == "self_audio_speaker_set_volume"
