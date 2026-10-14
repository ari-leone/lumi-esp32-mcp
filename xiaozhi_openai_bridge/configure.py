"""Generate local settings once; never overwrite the existing token."""
import json
import argparse
import re
import ipaddress
import secrets
import socket
from pathlib import Path

path = Path(__file__).with_name("local_config.json")
if not path.exists():
    parser=argparse.ArgumentParser(description='Preparar configuración privada del puente.')
    parser.add_argument('--device-id',required=True,help='MAC de tu placa; no se incluye en el repositorio.')
    parser.add_argument('--pc-ip',help='IPv4 del PC; si se omite, se detecta la interfaz local.')
    args=parser.parse_args()
    if not re.fullmatch(r'(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}',args.device_id):
        parser.error('device-id debe ser una MAC con seis pares separados por dos puntos.')
    if args.pc_ip:
        try:address=str(ipaddress.IPv4Address(args.pc_ip))
        except ipaddress.AddressValueError:parser.error('pc-ip debe ser una dirección IPv4 válida.')
    else:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("192.168.1.1", 80))
            address = sock.getsockname()[0]
    path.write_text(json.dumps({
        "pc_ip": address, "port": 8002, "device_id": args.device_id.lower(),
        "token": secrets.token_urlsafe(32), "model": "gpt-realtime-2.1", "voice": "marin",
        "backend":"live", "notebook_provider":"pc_mcp", "live_backend_model":"gpt-5.6-luna",
    }, indent=2), encoding="utf-8")
print("Configuración local preparada. Clave API y token no mostrados.")
