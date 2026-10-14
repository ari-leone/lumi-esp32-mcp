# Firmware actual de Lumi · PC y MCP

Placa Waveshare ESP32-S3-Touch-AMOLED-2.16, XiaoZhi v2.4.2 con ESP-IDF 6.0.2.
Fuentes propias en esta carpeta; parche acumulado reproducible: lumi-pc-mcp.patch.
La fuente original está en .deps/xiaozhi-source-v2.4.2.zip.

## Funciones que se conservan

- Lumi en la pantalla, estados es-ES y controles táctiles.
- Zona táctil 384 × 336: un toque abre; otro cierra la conversación.
- Separación de 450 ms entre toques y cierre seguro de reproducción pendiente.
- BOOT/botón izquierdo: inicia, cierra escuchando e interrumpe al hablar.
- Atenuación a los 60 segundos; apagado automático por inactividad deshabilitado.
- Micrófono, altavoz, Wi-Fi y MCP de volumen/estado del dispositivo.

## Notas y tareas

Residen exclusivamente en la aplicación del PC, conectada al puente por MCP.
Se retiraron del firmware las cinco herramientas self.notes.* y su almacén NVS.
La tabla lumi-16m.csv deja 0x10000-0x20000 sin asignar: 64 KB para usos futuros.
No se desplazan ni amplían automáticamente las otras particiones.

La variante anterior del bloc está en el respaldo privado
.build/firmware-before-remove-local-notes-20261014. No forma parte de las
fuentes actuales. La nota existente se migró antes de retirar el almacén.

## Compilar y verificar

Conserva el SDK y sus herramientas en .deps. Usa Python 3.12 del entorno
idf6.0_py3.12_env, activa ESP-IDF y compila la variante de esta placa en es-ES.
La ruta corta de compilación usada es:
%TEMP%/lumi-fw-20261004/xiaozhi-esp32-2.4.2.

build_current.ps1 activa el entorno correcto, reutiliza las versiones fijadas
y habilita los archivos de argumentos de Ninja para evitar el límite de
longitud de órdenes de Windows. Compila y verifica; no graba la placa.

save_patch.py --source <fuente-actual> --output lumi-pc-mcp.patch genera el
parche contra el ZIP original. verify_pc_mcp_build.py <directorio-build>
comprueba chip, checksum, SHA256, idioma, controles, ausencia de notas y que
todas las particiones ajenas al bloc conservan sus direcciones y tamaños.

La instalación escribe exclusivamente tabla 0x8000 y aplicación 0x20000 en la
partición activa verificada. No usar merged-binary.bin ni erase-flash: borrarían
configuración o recursos. El borrado del antiguo almacén se limita al rango
0x10000, longitud 0x10000, después de comprobar su respaldo y la migración.

RESPALDOS_LUMI.md documenta recuperación. capture_board_log.py omite texto de
conversaciones y URLs; usa el Python del SDK para acceder a COM3. La aplicación
de voz no utiliza USB para audio: el transporte habitual es Wi-Fi.
