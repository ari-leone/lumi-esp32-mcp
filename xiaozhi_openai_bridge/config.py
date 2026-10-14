import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def settings():
    path = ROOT / "local_config.json"
    if not path.exists():
        raise RuntimeError("Ejecuta primero configure.py")
    result = json.loads(path.read_text(encoding="utf-8"))
    key = os.environ.get("OPENAI_API_KEY", "") or result.get('api_key','')
    if not key or not key.startswith("sk-"):
        raise RuntimeError("Falta una clave OpenAI válida en OPENAI_API_KEY o la configuración privada del puente.")
    result["api_key"] = key
    result["backend"] = os.environ.get("XIAOZHI_BACKEND", result.get("backend", "realtime"))
    return result
