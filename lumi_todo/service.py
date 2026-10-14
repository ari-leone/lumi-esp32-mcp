"""Lumi persistence and rules. Shared by HTTP today and an MCP adapter later."""
import hashlib
import json
import sqlite3
import uuid
from contextlib import contextmanager, closing
from datetime import date, datetime, timezone
from pathlib import Path


class AppError(Exception):
    def __init__(self, code, message, status=400):
        self.code, self.message, self.status = code, message, status
        super().__init__(message)


def now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS items (
                    id TEXT PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('task','note')),
                    title TEXT NOT NULL, text TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','completed')),
                    due_date TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    completed_at TEXT, deleted_at TEXT, version INTEGER NOT NULL DEFAULT 1,
                    source TEXT NOT NULL DEFAULT 'pc'
                );
                CREATE INDEX IF NOT EXISTS items_views ON items(kind,deleted_at,status,updated_at);
                CREATE TABLE IF NOT EXISTS requests (
                    id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, result TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS migrations (version INTEGER PRIMARY KEY);
                INSERT OR IGNORE INTO migrations VALUES(1);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def validate(self, data):
        title, text = data.get('title'), data.get('text', '')
        if not isinstance(title, str) or not title.strip() or len(title.strip()) > 200:
            raise AppError('validation', 'El título debe tener entre 1 y 200 caracteres.')
        if not isinstance(text, str) or len(text) > 20000:
            raise AppError('validation', 'El contenido admite hasta 20.000 caracteres.')
        due = data.get('due_date') or None
        if due is not None:
            try:
                if not isinstance(due, str) or date.fromisoformat(due).isoformat() != due:
                    raise ValueError()
            except ValueError:
                raise AppError('validation', 'La fecha debe tener formato AAAA-MM-DD.')
        return title.strip(), text, due

    def get(self, item_id, db=None):
        if db is None:
            with self.connect() as connection:
                return self.get(item_id, connection)
        row = db.execute('SELECT * FROM items WHERE id=?', (item_id,)).fetchone()
        if row is None:
            raise AppError('not_found', 'Este elemento ya no existe.', 404)
        return dict(row)

    def list(self, view='pending', query='', offset=0, limit=50):
        clauses, values = [], []
        if view == 'trash':
            clauses.append('deleted_at IS NOT NULL')
        elif view in ('pending', 'completed', 'notes'):
            clauses.append('deleted_at IS NULL')
            clauses.append('kind=?')
            values.append('note' if view == 'notes' else 'task')
            if view != 'notes':
                clauses.append('status=?')
                values.append(view)
        else:
            raise AppError('validation', 'Vista desconocida.')
        with self.connect() as db:
            rows = [dict(row) for row in db.execute(
                'SELECT * FROM items WHERE ' + ' AND '.join(clauses) +
                ' ORDER BY CASE WHEN due_date IS NULL THEN 1 ELSE 0 END,due_date,updated_at DESC', values)]
        # Python casefold keeps accent-bearing uppercase searches consistent in SQLite.
        terms = query.casefold().split()
        rows = [row for row in rows if all(t in (row['title']+' '+row['text']).casefold() for t in terms)]
        return {'items': rows[offset:offset+limit], 'total': len(rows),
                'next_offset': offset+limit if offset+limit < len(rows) else None}

    def counts(self):
        with self.connect() as db:
            rows = db.execute('SELECT kind,status,deleted_at FROM items').fetchall()
        counts = dict(pending=0, completed=0, notes=0, trash=0)
        for row in rows:
            key = 'trash' if row['deleted_at'] else 'notes' if row['kind']=='note' else row['status']
            counts[key] += 1
        return counts

    def mutate(self, action, payload, item_id=None):
        if not isinstance(payload, dict):
            raise AppError('validation', 'Se esperaba un objeto JSON.')
        request_id = payload.get('request_id')
        if not isinstance(request_id, str) or not 1 <= len(request_id) <= 128:
            raise AppError('validation', 'Falta un request_id válido para esta operación.')
        fingerprint = hashlib.sha256(json.dumps([action,item_id,payload], sort_keys=True).encode()).hexdigest()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            previous = db.execute('SELECT * FROM requests WHERE id=?', (request_id,)).fetchone()
            if previous:
                if previous['fingerprint'] != fingerprint:
                    raise AppError('conflict', 'Este identificador de petición ya se usó para otra operación.', 409)
                return json.loads(previous['result'])
            if action == 'create':
                title, text, due = self.validate(payload)
                kind = payload.get('kind')
                if kind not in ('task', 'note'):
                    raise AppError('validation', 'El tipo debe ser task o note.')
                source=payload.get('source','pc')
                if source not in ('pc','lumi','import'):
                    raise AppError('validation','Origen no válido.')
                item_id, stamp = str(uuid.uuid4()), now()
                db.execute('INSERT INTO items(id,kind,title,text,due_date,created_at,updated_at,source) VALUES(?,?,?,?,?,?,?,?)',
                           (item_id,kind,title,text,due if kind=='task' else None,stamp,stamp,source))
            else:
                item = self.get(item_id, db)
                if type(payload.get('expected_version')) is not int or payload['expected_version'] != item['version']:
                    raise AppError('conflict', 'El elemento ha cambiado. Recarga la versión actual; tu borrador se conserva.', 409)
                if action != 'restore' and item['deleted_at']:
                    raise AppError('conflict', 'Este elemento está en la papelera. Restáuralo primero.', 409)
                changes = {}
                if action == 'update':
                    title,text,due = self.validate(payload)
                    changes = dict(title=title,text=text,due_date=due if item['kind']=='task' else None)
                elif action in ('complete', 'reopen'):
                    if item['kind'] != 'task':
                        raise AppError('validation', 'Solo las tareas se pueden completar.')
                    target = 'completed' if action=='complete' else 'pending'
                    if item['status'] != target:
                        changes = dict(status=target,completed_at=now() if target=='completed' else None)
                elif action == 'delete':
                    changes = dict(deleted_at=now())
                elif action == 'restore':
                    if item['deleted_at']:
                        changes = dict(deleted_at=None)
                else:
                    raise AppError('validation', 'Operación desconocida.')
                if changes:
                    changes.update(updated_at=now(),version=item['version']+1)
                    db.execute('UPDATE items SET '+','.join(k+'=?' for k in changes)+' WHERE id=?',
                               [*changes.values(),item_id])
            result = self.get(item_id, db)
            db.execute('INSERT INTO requests VALUES(?,?,?)',(request_id,fingerprint,json.dumps(result)))
            return result

    def export(self):
        with self.connect() as db:
            rows = [dict(row) for row in db.execute('SELECT * FROM items ORDER BY created_at,id')]
        return dict(format='lumi-todo', schema_version=1, exported_at=now(), items=rows)

    def import_data(self, data):
        if not isinstance(data,dict) or data.get('format')!='lumi-todo' or data.get('schema_version')!=1:
            raise AppError('validation', 'Selecciona una exportación JSON de Lumi compatible.')
        records = data.get('items')
        if not isinstance(records,list) or len(records)>10000:
            raise AppError('validation', 'La importación admite hasta 10.000 elementos.')
        fields = ['id','kind','title','text','status','due_date','created_at','updated_at','completed_at','deleted_at','version','source']
        imported, skipped = 0, 0
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            for record in records:
                if not isinstance(record,dict) or any(k not in record for k in fields):
                    raise AppError('validation','Hay un registro incompleto en la exportación.')
                self.validate(record)
                try:
                    uuid.UUID(record['id'])
                    if record['kind'] not in ('task','note') or record['status'] not in ('pending','completed'):
                        raise ValueError()
                    if type(record['version']) is not int or record['version']<1 or record['source'] not in ('pc','lumi','import'):
                        raise ValueError()
                    for key in ('created_at','updated_at','completed_at','deleted_at'):
                        if record[key] is None and key in ('completed_at','deleted_at'):
                            continue
                        if datetime.fromisoformat(record[key]).utcoffset() is None:
                            raise ValueError()
                    if record['kind']=='note' and record['due_date']:
                        raise ValueError()
                except (ValueError,TypeError,AttributeError):
                    raise AppError('validation','Hay metadatos inválidos en la exportación.')
                existing = db.execute('SELECT * FROM items WHERE id=?',(record['id'],)).fetchone()
                if existing:
                    if dict(existing) != {key:record[key] for key in fields}:
                        raise AppError('conflict','Un elemento importado tiene una versión diferente. No se ha sobrescrito ningún dato.',409)
                    skipped += 1
                    continue
                db.execute('INSERT INTO items('+','.join(fields)+') VALUES('+','.join('?' for _ in fields)+')',
                           [record[k] for k in fields])
                imported += 1
        return dict(imported=imported,skipped=skipped)

    def backup(self):
        folder = self.path.parent / 'backups'
        folder.mkdir(exist_ok=True)
        path = folder / ('lumi-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')+'.sqlite3')
        with self.connect() as source, closing(sqlite3.connect(path)) as destination:
            source.backup(destination)
            if destination.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
                raise AppError('storage','No se pudo verificar la copia.',500)
        return path
