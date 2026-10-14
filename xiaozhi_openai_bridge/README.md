# Puente experimental XiaoZhi → OpenAI

La clave se obtiene de `OPENAI_API_KEY` o del campo `api_key` de
`local_config.json`, archivo privado excluido de Git. El puente ya no depende
de los proyectos Arduino antiguos, eliminados el 14/10/2026.

## Modos Realtime y GPT-Live

El usuario confirmó voz y subida/bajada de volumen MCP con GPT-Live en la placa
el 29/09/2026. Véase `../VALIDACION_GPT_LIVE.md`. Nueve pruebas automáticas pasan.

`local_config.json` admite `"backend": "realtime"` (predeterminado) o
`"backend": "live"`. También se puede seleccionar para un proceso mediante
`XIAOZHI_BACKEND`. Cambiar de modo requiere reiniciar el puente; la URL de la
placa permanece igual. `/health` indica el modo configurado.

El modo Live usa `gpt-live-1` y delegación Responses con `gpt-5.6-luna` para
las herramientas MCP permitidas. La clave sigue en el PC. `check_live.py`
comprueba inicio y cierre; `check_roundtrip.py --volume-test` comprueba una
orden sintética de volumen con una placa simulada (requiere generar antes el
WAV con `check_api.py --speak --volume-command`).

Con el firmware XiaoZhi actual se conservan turnos alternos: durante la salida
se envía silencio a Live, ya que la placa deja de capturar el micrófono. No es
una implementación de interrupción de voz en dúplex completo. Live no emite
un evento de fin de audio: se detectan silencios de 600 ms o inactividad de
salida de 800 ms para volver a escuchar. Es una heurística que requiere prueba
física con frases largas y pausas. Las sesiones siguen limitadas a 15 minutos.

Documentación oficial:
- https://developers.openai.com/api/docs/guides/voice-websockets?api=live
- https://developers.openai.com/api/docs/guides/live-delegation

La versión estable sigue siendo el firmware XiaoZhi 2.4.2 guardado en Arduino.
El 29/09/2026 el usuario confirmó voz y volumen MCP con este puente en la placa.
Tras ajustar la temporización de audio, confirmó que se escucha mejor.
Seis pruebas automáticas pasan. Véase `../VALIDACION_PUENTE_REALTIME.md`.

## Qué hace

Recibe paquetes Opus de XiaoZhi por WebSocket versión 1, los convierte a PCM16 mono
24 kHz para OpenAI Realtime y devuelve Opus a la placa. Implementa detección de
fin de frase en el servidor y parada manual. La primera versión es de turnos
alternos: no envía al modelo audio del micrófono mientras reproduce una respuesta.
Al interrumpir, cancela audio pendiente; aún no sincroniza la truncación del
historial del modelo con el punto exacto escuchado por el usuario.

El PC actúa como cliente MCP del servidor MCP incluido en la placa. Descubre y
habilita solamente `self.get_device_status` y `self.audio_speaker.set_volume`.
No usa el antiguo archivo `mcp_action.json`, incompatible con este firmware.

## Configuración

El entorno aislado está en `../.deps/xiaozhi-bridge-venv`. Ejecutar `configure.py`
con su Python crea `local_config.json` (ignorado por Git). Mantener privada esa
configuración: contiene el token de acceso local. Cambiar `pc_ip` si cambia la IP.
La clave API se lee de `OPENAI_API_KEY` o del `secrets.h` del proyecto anterior;
no se envía a la placa. El uso de la API tiene su propia facturación.

`check_api.py` comprueba el acceso sin audio; `check_api.py --speak` solicita una
frase de prueba y guarda un WAV en `../.build/openai-prueba-voz.wav`.
Ejecutar las pruebas con `python -m pytest -q` desde esta carpeta.

Iniciar con `powershell -File start.ps1`. El puerto es 8002. No abrirlo a Internet.
El servidor exige el token y el Device-Id de esta placa; admite una sesión a la vez.
No guarda conversaciones ni audio de la placa. Límite de sesión: 15 minutos.

## Cambio de servidor (pendiente de validar físicamente)

Solo después de pasar las pruebas, abrir el modo Wi-Fi de la placa y consultar su
formulario avanzado. La URL OTA local tiene el formato
`http://IP_DEL_PC:8002/ota/TOKEN_LOCAL`. No es una descarga de firmware: devuelve
la configuración del WebSocket, incluido su token. No modificar la URL aún si
el formulario real no ofrece esta opción. Conservar la URL original antes de
cambiarla para volver al servicio XiaoZhi. Puede ser necesario permitir el puerto
8002 en el firewall de Windows exclusivamente en la red privada.

## Referencias

- https://github.com/78/xiaozhi-esp32/blob/main/docs/websocket.md
- https://github.com/78/xiaozhi-esp32/blob/main/docs/mcp-protocol.md
- https://developers.openai.com/api/docs/guides/realtime-conversations
