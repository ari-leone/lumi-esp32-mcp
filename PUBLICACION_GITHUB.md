# Archivos incluidos y privacidad

Este repositorio contiene únicamente código mantenido, pruebas con datos
ficticios, documentación genérica y recursos gráficos del personaje Lumi.

## No incluidos

- Claves API, tokens reales, contraseñas Wi-Fi y configuración del dispositivo.
- Base SQLite, notas, tareas, exportaciones y copias de seguridad.
- Audio, vídeo, transcripciones y registros de conversaciones.
- Firmware compilado, NVS, volcados de flash y respaldos de fábrica.
- Informes de diagnóstico privados, capturas de la aplicación y rutas personales.
- SDK descargado, dependencias instaladas y ejemplos de fabricantes.

La configuración real local_config.json permanece solo en el equipo. El archivo
local_config.example.json contiene identificadores ficticios y un marcador de
token, nunca la configuración utilizada por una placa real.

La lista permitida de .gitignore limita los archivos elegibles. Antes de cada
envío, revisa el contenido preparado con git diff --cached y git status.
No uses git add -f para incluir respaldos o archivos ignorados.

No se ha añadido al historial ningún archivo privado previo. La revisión inicial
incluyó búsqueda de los valores sensibles reales en memoria, patrones de claves,
material privado y rutas personales, sin imprimir los valores secretos.

El aviso de licencia del firmware upstream se conserva en
tools/firmware_lumi/LICENSE. Los recursos y código de dependencias externas no
se incluyen; deben obtenerse de sus fuentes correspondientes.
