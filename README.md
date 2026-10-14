# Lumi · ESP32, voz y notas con MCP

Asistente de voz para Waveshare ESP32-S3-Touch-AMOLED-2.16, con personaje Lumi,
interfaz local de notas y tareas y servidor MCP conectado al puente de voz.

## Componentes

- lumi_todo: aplicación en español, API local, SQLite y servidor MCP stdio.
- xiaozhi_openai_bridge: audio y voz por Wi-Fi, cliente MCP y herramientas.
- tools/firmware_lumi: modificaciones reproducibles de XiaoZhi v2.4.2 para
  controles táctiles, idioma español y almacenamiento externo de notas.
- assets/lumi: recursos gráficos del personaje.

El firmware actual no almacena notas ni tareas en la placa. Volumen y estado
siguen como herramientas de la placa; notas y tareas se guardan en SQLite del
PC. Las fechas límite no programan alarmas.

## Uso local

La aplicación visual usa Python 3.11 o posterior y su biblioteca estándar.
Ejecuta lumi_todo/Abrir Lumi.cmd o python lumi_todo/server.py y abre
http://127.0.0.1:8765. Los datos se guardan por defecto en
%LOCALAPPDATA%\LumiNotes; las copias manuales están en la subcarpeta backups.

Para usar voz, crea un entorno Python e instala
xiaozhi_openai_bridge/requirements.txt. Prepara local_config.json en la carpeta
del puente, siguiendo local_config.example.json, y configura tu dirección LAN,
identificador de placa y token propio. La clave de voz se proporciona mediante
OPENAI_API_KEY o el campo privado api_key de local_config.json. No compartas
ese archivo. El generador configure.py acepta --device-id y no sobrescribe una
configuración existente.

lumi_todo/Abrir Lumi con voz.cmd inicia ambos servicios en Windows. El lanzador
busca el entorno del puente en .deps/xiaozhi-bridge-venv. También puedes ejecutar
uvicorn desde tu entorno, en la carpeta del puente y en tu dirección LAN.
La placa debe apuntar al endpoint OTA/WebSocket de ese puente con su token.

La voz necesita PC encendido, Wi-Fi, Internet y proveedor de voz disponible.
La aplicación visual se usa sin placa ni Internet.

## Firmware

Consulta tools/firmware_lumi/README.md. El SDK, sus componentes, los binarios y
los respaldos no se incluyen. El parche se aplica sobre la fuente upstream
correspondiente. Grabar requiere comprobar placa, partición activa y respaldos
locales; no publiques volcados de flash ni NVS porque pueden contener secretos.

## Pruebas

python -m unittest discover -s lumi_todo -p 'test_service.py' -v

Con las dependencias del puente instaladas:

python -m unittest discover -s lumi_todo -p 'test_*.py' -v
python -m pytest xiaozhi_openai_bridge/test_bridge.py xiaozhi_openai_bridge/test_live.py xiaozhi_openai_bridge/test_pc_mcp.py -q -p no:cacheprovider

Las pruebas usan bases temporales y datos ficticios. Las pruebas físicas se
realizan por separado. Lee PUBLICACION_GITHUB.md para conocer las exclusiones
aplicadas a esta distribución.
