"""Explicit hardware notebook smoke test; run manually, not during pytest.

Creates only its own marked temporary note. A second phase verifies it after
a hardware restart and removes the marked note, leaving user notes intact.
"""
import argparse
import json
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import time

from config import settings

MARKER = "Prueba técnica Lumi 20261011"
TEXT = "Verificación: café, mañana y número 2."


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("exercise", "verify"))
    args = parser.parse_args()
    cfg = settings()
    report = Path(__file__).resolve().parent.parent / ".build/notebook-device-test.json"

    def rpc(operation, arguments, expect_error=False):
        request = Request(f"http://{cfg['pc_ip']}:{cfg['port']}/notebook/tool",
                          data=json.dumps({"name": "self.notes." + operation,
                                           "arguments": arguments}).encode(),
                          headers={"authorization": "Bearer " + cfg["token"],
                                   "content-type": "application/json"})
        deadline = time.monotonic() + 60
        while True:
            try:
                with urlopen(request, timeout=12) as response:
                    result = json.load(response)
                break
            except HTTPError as error:
                # 409 is returned before forwarding anything to the device.
                if error.code != 409 or time.monotonic() >= deadline:
                    raise
                time.sleep(0.5)
        assert bool(result.get("isError")) == expect_error, "Unexpected board tool status"
        if expect_error:
            return
        return json.loads(next(item["text"] for item in result["content"] if item["type"] == "text"))

    if args.phase == "exercise":
        existing = rpc("list", {"query": ""})["notes"]
        assert not any(n["title"] == MARKER for n in existing), "An earlier test note remains"
        created = rpc("create", {"title": MARKER, "text": "Texto inicial de prueba."})
        note_id = created["id"]
        # Save the id immediately so a later test failure cannot lose its identity.
        report.write_text(json.dumps({"id": note_id, "marker": MARKER, "phase": "created"}), encoding="utf-8")
        assert rpc("get", {"id": note_id}) == created
        updated = rpc("update", {"id": note_id, "title": "", "text": TEXT})
        assert updated == {"id": note_id, "title": MARKER, "text": TEXT}
        assert note_id in [n["id"] for n in rpc("list", {"query": "CAFÉ"})["notes"]]
        rpc("update", {"id": note_id, "text": "x" * 513}, expect_error=True)
        assert rpc("get", {"id": note_id}) == updated
        rpc("delete", {"id": 2147483647}, expect_error=True)
        assert rpc("get", {"id": note_id}) == updated
        report.write_text(json.dumps({"id": note_id, "marker": MARKER, "phase": "exercise_passed"}), encoding="utf-8")
        print("Crear, leer, editar, buscar con acentos y rechazo de errores: correctos en la placa.")
    else:
        saved = json.loads(report.read_text(encoding="utf-8"))
        assert saved["marker"] == MARKER and saved["phase"] == "exercise_passed"
        note_id = saved["id"]
        assert rpc("get", {"id": note_id}) == {"id": note_id, "title": MARKER, "text": TEXT}
        assert rpc("delete", {"id": note_id}) is True
        rpc("get", {"id": note_id}, expect_error=True)
        assert note_id not in [n["id"] for n in rpc("list", {"query": ""})["notes"]]
        saved.update({"phase": "all_passed", "persistent_after_restart": True, "temporary_note_deleted": True})
        report.write_text(json.dumps(saved, indent=2), encoding="utf-8")
        print("Persistencia tras reinicio y borrado: correctos. Nota de prueba eliminada.")


if __name__ == "__main__":
    main()
