# Lumi · Notas y tareas

Aplicación local en español para gestionar tareas y notas sin la placa ni Internet.
Servidor MCP local incorporado y puente de voz configurado para compartir esta
base de datos. Las alarmas aún no están implementadas. El firmware se conserva.

## Abrir

Haz doble clic en **Abrir Lumi.cmd**. El lanzador inicia un servicio oculto y abre
http://127.0.0.1:8765. Si ya está iniciado, reutiliza la instancia. Cerrar la pestaña
no detiene el servicio. Al reiniciar Windows, vuelve a usar el lanzador.

Requiere Python 3.11 o posterior. No necesita instalar paquetes: usa su biblioteca
estándar. El lanzador busca el Python del entorno de Codex, el del puente y Python
del sistema, en ese orden.

Para usar también la placa, abre **Abrir Lumi con voz.cmd**. Arranca la aplicación
y el puente de voz sin ventanas adicionales, verifica MCP y reutiliza las
instancias ya activas. La voz necesita PC encendido, Wi-Fi, Internet y el servicio
de voz. El bloc visual sigue funcionando sin ellos. La configuración del puente
está en `xiaozhi_openai_bridge/local_config.json`, archivo privado fuera de Git.
Si DHCP cambia la IP del PC, deben corregirse las URLs de la placa y el puente:
el lanzador lo detecta y no intenta iniciar en una IP ajena.

```powershell
.\start.ps1 -Port 8765
# Carpeta de datos alternativa (solo para una instancia nueva)
.\start.ps1 -Port 8766 -DataDir 'C:\ruta\datos'
```

## Funciones

- Crear y editar tareas; completar y reabrir sin duplicarlas.
- Fechas límite de calendario, con indicación de vencidas según Europe/Madrid.
  No programan avisos.
- Crear y editar notas de hasta 20.000 caracteres; títulos hasta 200.
- Buscar títulos y contenido, con mayúsculas y acentos; listados de 50 en 50.
- Papelera recuperable: no hay borrado definitivo en esta versión.
- Exportar todo a JSON, importar una exportación de esta aplicación y crear una
  copia SQLite coherente y verificada. Importar no sobrescribe versiones distintas:
  un conflicto cancela toda la importación. Reimportar datos idénticos no duplica.
- Detectar ediciones simultáneas y conservar el borrador cuando hay un conflicto.
- Recargar listas cada 15 segundos mientras la ventana está visible y no editas.

## Datos y copias

Por defecto, los datos están en **%LOCALAPPDATA%\LumiNotes\lumi.sqlite3**, fuera de
OneDrive. Las copias manuales se guardan en **%LOCALAPPDATA%\LumiNotes\backups**.
Para abrir la carpeta, usa **Abrir carpeta de datos.cmd**, o pulsa Win+R y pega
`%LOCALAPPDATA%\LumiNotes`. SQLite no se abre como página web: para ver y editar
las notas, usa http://127.0.0.1:8765.
El 14/10/2026 se importó la única nota presente en la placa, con contenido y hash
verificados. Después se retiró el bloc interno y se borró su rango de 64 KB.
La copia histórica solo se conserva en el respaldo privado del PC; las nuevas notas y tareas por
voz se guardan únicamente en el PC. No hay datos de demostración en la base.
Las exportaciones incluyen la papelera. No se guarda audio ni conversaciones.
No hay copia automática diaria ni inicio automático en Windows en esta versión.

Para detener el servicio, usa el Administrador de tareas: el PID se conserva en
`%LOCALAPPDATA%\LumiNotes\server.pid`. Verifica que ese PID corresponde a Python
ejecutando `lumi_todo\server.py` antes de finalizarlo.

Para restaurar una copia: detén Lumi, conserva la carpeta de datos actual, y arranca
con una carpeta nueva que contenga la copia renombrada a `lumi.sqlite3`. Nunca
reemplaces el archivo de una instancia en marcha ni mezcles WAL/SHM de otra base.
También puedes importar una exportación JSON en una carpeta de datos vacía.

## Arquitectura MCP

`service.py` es la única capa de reglas y persistencia. `server.py` adapta HTTP
local y sirve `static/`. `mcp_server.py` usa el SDK oficial MCP fijado en 1.30.0,
publica 12 herramientas por stdio y llama a la misma Store y ruta SQLite. No abre
un puerto MCP a la red. El SDK está instalado en el entorno del puente; la
aplicación visual conserva su independencia de paquetes externos.

- `Store.list(view, query, offset, limit)` / `get(id)` / `counts()`.
- `Store.mutate(action, payload, item_id=None)` con `request_id` obligatorio;
  cambios con `expected_version`. Operaciones create/update/complete/reopen/delete/restore.
- UUID estables, transacciones, versiones y peticiones idempotentes; confirmación
  después de commit. Los errores tienen código, mensaje y estado HTTP.
- `Store.export()` / `import_data(data)` / `backup()`.
- Fuente activa: PC. HTTP escucha exclusivamente en 127.0.0.1; Host y Origin
  restringidos. Las escrituras requieren JSON y cabecera X-Lumi-Client: local.
  El texto se renderiza como texto, no HTML. Sin recursos ni servicios externos.

API: GET `/api/health`, `/api/counts`, `/api/items?view=pending&q=...`,
`/api/items/{id}`, `/api/export`; POST `/api/items`, `/api/items/{id}/{action}`,
`/api/import`, `/api/backup`.

`xiaozhi_openai_bridge/mcp_provider.py` administra el proceso MCP en una tarea
propietaria independiente de las conversaciones. Descubre herramientas antes de
anunciarlas, reconecta sin repetir escrituras y evita pasar las credenciales de
voz al proceso del bloc. Volumen y estado siguen en la placa. Las herramientas
antiguas de notas se retiraron del firmware y del catálogo de voz.
`/notebook/tool` conserva compatibilidad de lectura con firmware antiguo para
recuperación, pero la placa actual ya no tiene ese almacén ni esas herramientas.

La voz anuncia `notes_create/list/get/update/delete` y
`tasks_create/list/get/update/delete/complete/reopen`. El puente asigna claves de
petición estables por llamada; el modelo usa versiones e IDs consultados. Una
caída del bloc no guarda en la placa como alternativa ni confirma falsamente.
Los listados MCP devuelven resúmenes; get recupera el contenido específico.

`board_migration.py` exporta coherentemente por la ruta de lectura de la placa,
crea una copia previa e importa en transacción. Conserva una correspondencia
dispositivo/id antiguo → UUID y hash en `board_imports`. Repetir una importación
idéntica no duplica; versiones diferentes generan conflicto. Exportaciones de la
placa y respaldos NVS son privados y se guardaron en `.build` excluido de Git.

SDK y transporte: [documentación oficial](https://py.sdk.modelcontextprotocol.io/v1/client/).
Se mantiene la línea 1.x fijada para compatibilidad del adaptador probado; no
actualizar automáticamente a 2.x sin revisar su cambio de API y protocolo.

Para reversión de código/configuración, se conserva un respaldo privado en
`.build/mcp-preintegration-20261014`. Conserva primero las nuevas notas del PC;
volver al proveedor board no las traslada a la placa. Mantén la dirección actual
de tu PC incluso al recuperar la configuración anterior.

## Verificación

```powershell
python -m unittest discover -s lumi_todo -p 'test_service.py' -v
# Con el Python del puente, que tiene MCP instalado:
.\.deps\xiaozhi-bridge-venv\Scripts\python.exe -m unittest discover -s lumi_todo -p 'test_*.py' -v
.\.deps\xiaozhi-bridge-venv\Scripts\python.exe -m pytest xiaozhi_openai_bridge/test_bridge.py xiaozhi_openai_bridge/test_live.py xiaozhi_openai_bridge/test_pc_mcp.py -q -p no:cacheprovider
```

Las pruebas utilizan bases temporales y no escriben en las notas personales.
