"""Check GPT-Live access without changing the running Realtime bridge."""
import asyncio
import json

from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus

from config import settings
from live_bridge import live_session_config


async def main():
    cfg = settings()
    try:
        async with connect(
            "wss://api.openai.com/v1/live/sessions",
            additional_headers={"Authorization": "Bearer " + cfg["api_key"]},
            open_timeout=15,
        ) as ws:
            await ws.send(json.dumps({"type": "session.start", "session": live_session_config(cfg)}))
            async with asyncio.timeout(25):
                async for raw in ws:
                    event = json.loads(raw)
                    if event["type"] == "error":
                        error = event.get("error", {})
                        print("GPT-Live error:", error.get("code", "unknown"))
                        return 1
                    if event["type"] == "session.started":
                        print("GPT-Live: sesión iniciada correctamente.")
                        await ws.send(json.dumps({"type": "session.close"}))
                    if event["type"] == "session.closed":
                        print("GPT-Live: sesión cerrada correctamente.")
                        return 0
    except InvalidStatus as error:
        print("GPT-Live HTTP:", error.response.status_code)
        # Only print structured API error codes, never headers or credentials.
        try:
            body = json.loads(error.response.body)
            print("Código:", body.get("error", {}).get("code", "unknown"))
        except (ValueError, TypeError):
            pass
    except Exception as error:
        print("GPT-Live conexión:", type(error).__name__)
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
