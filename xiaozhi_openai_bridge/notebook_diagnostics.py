"""Local-only MCP session for explicit hardware notebook verification.

Selected only with XIAOZHI_BACKEND=device_test. Audio packets are discarded;
no audio, transcripts, or personal note contents are logged or sent to an API.
"""
import asyncio
import json

from server import Bridge


class NotebookDiagnostics(Bridge):
    async def event(self, kind, **kwargs):
        pass

    async def device_loop(self):
        while True:
            message = await self.device.receive()
            if message["type"] == "websocket.disconnect":
                return
            if message.get("bytes") is not None:
                continue
            payload = json.loads(message.get("text", "{}"))
            if payload.get("type") != "mcp":
                continue
            response = payload.get("payload", {})
            pending = self.pending.get(response.get("id"))
            if pending is not None and not pending.done():
                if "error" in response:
                    pending.set_exception(RuntimeError(str(response["error"].get("message", "La placa rechazó la operación."))))
                else:
                    pending.set_result(response.get("result", {}))

    async def run(self, mcp, on_session_ending=None):
        reader = asyncio.create_task(self.device_loop())
        try:
            await self.discover()
            await reader
        finally:
            if on_session_ending is not None:
                on_session_ending()
            reader.cancel()
            await asyncio.gather(reader, return_exceptions=True)
