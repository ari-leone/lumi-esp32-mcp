"""Local-only web adapter; deliberately independent of the voice bridge."""
import argparse
import json
import mimetypes
import os
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from service import AppError, Store

STATIC = Path(__file__).parent / 'static'


def handler_for(store, port):
    allowed_hosts = {f'127.0.0.1:{port}', f'localhost:{port}'}
    allowed_origins = {'http://'+host for host in allowed_hosts}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            # No note contents, queries, or credentials in logs.
            pass

        def send(self, status, content, content_type='application/json; charset=utf-8', extra=None):
            if not isinstance(content, bytes):
                content = json.dumps(content, ensure_ascii=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type',content_type)
            self.send_header('Content-Length',str(len(content)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Referrer-Policy','no-referrer')
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            for key,value in (extra or {}).items():
                self.send_header(key,value)
            self.end_headers()
            self.wfile.write(content)

        def handle_request(self, mutation=False):
            try:
                if self.headers.get('Host') not in allowed_hosts:
                    raise AppError('access','Host no autorizado.',403)
                origin = self.headers.get('Origin')
                if origin and origin not in allowed_origins:
                    raise AppError('access','Origen no autorizado.',403)
                if self.headers.get('Sec-Fetch-Site') == 'cross-site':
                    raise AppError('access','Acceso externo no autorizado.',403)
                payload = None
                if mutation:
                    if self.headers.get('X-Lumi-Client')!='local' or self.headers.get('Content-Type','').split(';')[0]!='application/json':
                        raise AppError('access','Solicitud local JSON requerida.',403)
                    try:
                        length = int(self.headers.get('Content-Length',0))
                        if not 0 < length <= 10_000_000:
                            raise AppError('validation','Tamaño de petición inválido.',413)
                        payload = json.loads(self.rfile.read(length))
                    except (ValueError,UnicodeDecodeError):
                        raise AppError('validation','El JSON no es válido.')
                url = urlsplit(self.path)
                path = url.path
                if not mutation:
                    if path=='/api/health':
                        return self.send(200,dict(app='lumi-todo',status='ok',provider='pc',schema_version=1))
                    if path=='/api/counts':
                        return self.send(200,store.counts())
                    if path=='/api/items':
                        q = parse_qs(url.query)
                        try:
                            offset=int(q.get('offset',['0'])[0]); limit=int(q.get('limit',['50'])[0])
                            if offset<0 or not 1<=limit<=100:
                                raise ValueError()
                        except ValueError:
                            raise AppError('validation','Paginación inválida.')
                        return self.send(200,store.list(q.get('view',['pending'])[0],q.get('q',[''])[0],offset,limit))
                    if path.startswith('/api/items/'):
                        return self.send(200,store.get(path.split('/')[-1]))
                    if path=='/api/export':
                        return self.send(200,store.export(),extra={'Content-Disposition':'attachment; filename="lumi-export.json"'})
                    files={'/':'index.html','/app.js':'app.js','/styles.css':'styles.css'}
                    if path in files:
                        file=STATIC/files[path]
                        return self.send(200,file.read_bytes(),mimetypes.guess_type(file)[0]+'; charset=utf-8')
                else:
                    if path=='/api/items':
                        return self.send(201,store.mutate('create',payload))
                    if path=='/api/import':
                        return self.send(200,store.import_data(payload))
                    if path=='/api/backup':
                        backup=store.backup()
                        return self.send(200,dict(saved=True,name=backup.name))
                    parts=path.strip('/').split('/')
                    if len(parts)==4 and parts[:2]==['api','items']:
                        return self.send(200,store.mutate(parts[3],payload,parts[2]))
                raise AppError('not_found','Ruta no encontrada.',404)
            except AppError as exc:
                self.send(exc.status,dict(error=exc.code,message=exc.message))
            except (sqlite3.Error,OSError):
                self.send(503,dict(error='storage',message='No se pudo acceder al almacenamiento. No se ha confirmado el guardado.'))
            except Exception:
                self.send(500,dict(error='internal',message='No se pudo completar la operación.'))

        def do_GET(self):
            self.handle_request()

        def do_POST(self):
            self.handle_request(True)

    return Handler


def main():
    parser=argparse.ArgumentParser(description='Lumi: notas y tareas locales')
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--data-dir',default=str(Path(os.environ.get('LOCALAPPDATA',str(Path.home()))) / 'LumiNotes'))
    args=parser.parse_args()
    store=Store(Path(args.data_dir)/'lumi.sqlite3')
    server=ThreadingHTTPServer(('127.0.0.1',args.port),handler_for(store,args.port))
    print(f'Lumi disponible en http://127.0.0.1:{args.port}',flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__=='__main__':
    main()
