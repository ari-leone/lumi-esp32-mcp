import json
import sqlite3
import tempfile
import threading
import unittest
import uuid
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from http.server import ThreadingHTTPServer

from service import Store, AppError
from server import handler_for


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.path=Path(self.temp.name)/'lumi.sqlite3'
        self.store=Store(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def create(self, **changes):
        payload=dict(kind='task',title='Comprar pan',text='En la panadería',request_id=str(uuid.uuid4()))
        payload.update(changes)
        return self.store.mutate('create',payload)

    def change(self,item,action,**extra):
        return self.store.mutate(action,dict(expected_version=item['version'],request_id=str(uuid.uuid4()),**extra),item['id'])

    def test_persistence_search_and_unicode(self):
        item=self.create(kind='note',title='Reunión de diseño',text='ÁRBOL y café 🐾')
        restarted=Store(self.path)
        self.assertEqual(restarted.get(item['id'])['text'],'ÁRBOL y café 🐾')
        self.assertEqual(restarted.list('notes','árbol CAFÉ')['total'],1)
        self.assertEqual(restarted.counts()['notes'],1)

    def test_completion_reopening_and_trash(self):
        item=self.create(due_date='2026-10-12')
        completed=self.change(item,'complete')
        self.assertIsNotNone(completed['completed_at'])
        same=self.change(completed,'complete')
        self.assertEqual(same['version'],completed['version'])
        reopened=self.change(same,'reopen')
        self.assertEqual(reopened['id'],item['id'])
        self.assertIsNone(reopened['completed_at'])
        deleted=self.change(reopened,'delete')
        self.assertEqual(self.store.list()['total'],0)
        self.assertEqual(self.store.list('trash')['total'],1)
        restored=self.change(deleted,'restore')
        self.assertEqual(restored['due_date'],'2026-10-12')
        self.assertEqual(self.store.list()['total'],1)

    def test_validation_and_no_partial_writes(self):
        for change in [dict(title='  '),dict(title='a'*201),dict(text='x'*20001),dict(due_date='2026-02-30'),dict(kind='bad')]:
            with self.assertRaises(AppError):self.create(**change)
        self.assertEqual(self.store.counts()['pending'],0)
        note=self.create(kind='note')
        with self.assertRaises(AppError):self.change(note,'complete')

    def test_idempotency_and_key_reuse(self):
        payload=dict(kind='task',title='Una sola tarea',request_id='same-request')
        first=self.store.mutate('create',payload)
        self.assertEqual(self.store.mutate('create',payload),first)
        self.assertEqual(self.store.counts()['pending'],1)
        payload['title']='Otro contenido'
        with self.assertRaises(AppError):self.store.mutate('create',payload)

    def test_concurrent_edits_only_one_wins(self):
        item=self.create()
        def write(title):
            try:return self.change(item,'update',title=title,text='')
            except AppError as exc:return exc.code
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(write,['Uno','Dos']))
        self.assertEqual(sum(isinstance(r,dict) for r in results),1)
        self.assertIn('conflict',results)
        self.assertEqual(self.store.get(item['id'])['version'],2)

    def test_pagination(self):
        for i in range(55):self.create(title=f'Tarea {i}')
        page=self.store.list(limit=50)
        self.assertEqual(len(page['items']),50)
        self.assertEqual(len(self.store.list(offset=page['next_offset'])['items']),5)

    def test_export_import_atomic_and_repeatable(self):
        item=self.create(kind='note')
        data=self.store.export()
        other=Store(Path(self.temp.name)/'other.sqlite3')
        self.assertEqual(other.import_data(data)['imported'],1)
        self.assertEqual(other.import_data(data)['skipped'],1)
        data['items'].insert(0,{**data['items'][0],'id':str(uuid.uuid4())})
        data['items'][1]['title']='Conflicto'
        with self.assertRaises(AppError):other.import_data(data)
        self.assertEqual(other.counts()['notes'],1)
        self.assertEqual(other.get(item['id'])['title'],item['title'])

    def test_backup_restoration(self):
        item=self.create(text='Información que debe sobrevivir')
        copy=self.store.backup()
        restored=Store(copy)
        self.assertEqual(restored.get(item['id']),item)
        with closing(sqlite3.connect(copy)) as db:self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')

    def test_locked_database_does_not_confirm_write(self):
        lock=sqlite3.connect(self.path)
        lock.execute('BEGIN IMMEDIATE')
        original=self.store.connect
        from contextlib import contextmanager
        @contextmanager
        def quick_connect():
            with original() as db:
                db.execute('PRAGMA busy_timeout=10')
                yield db
        self.store.connect=quick_connect
        try:
            with self.assertRaises(sqlite3.OperationalError):self.create()
        finally:lock.rollback();lock.close()
        self.assertEqual(self.store.counts()['pending'],0)


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        cls.store=Store(Path(cls.temp.name)/'http.sqlite3')
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),handler_for(cls.store,0))
        cls.port=cls.server.server_address[1]
        cls.server.RequestHandlerClass=handler_for(cls.store,cls.port)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.thread.join();cls.temp.cleanup()

    def call(self,path,body=None,headers=None):
        request=Request(f'http://127.0.0.1:{self.port}'+path,data=json.dumps(body).encode() if body is not None else None,
                        headers=headers or {})
        return urlopen(request,timeout=3)

    def test_health_and_static(self):
        with self.call('/api/health') as response:self.assertEqual(json.load(response)['app'],'lumi-todo')
        with self.call('/') as response:
            self.assertIn('Lumi'.encode(),response.read())
            self.assertIn("frame-ancestors 'none'",response.headers['Content-Security-Policy'])

    def test_reject_external_origins_hosts_and_simple_posts(self):
        for headers,body in [({'Origin':'https://evil.example'},None),({'Host':'evil.example'},None),({},{}),({'Content-Type':'application/json','X-Lumi-Client':'local','Origin':'https://evil.example'}, {})]:
            with self.assertRaises(HTTPError) as error:self.call('/api/items',body,headers)
            self.assertEqual(error.exception.code,403)

    def test_write_read_and_invalid_json_shape(self):
        headers={'Content-Type':'application/json','X-Lumi-Client':'local'}
        with self.call('/api/items',dict(kind='note',title='<script>alert(1)</script>',text='café',request_id=str(uuid.uuid4())),headers) as response:item=json.load(response)
        with self.call('/api/items/'+item['id']) as response:self.assertEqual(json.load(response)['text'],'café')
        with self.assertRaises(HTTPError) as error:self.call('/api/items',[],headers)
        self.assertEqual(error.exception.code,400)

    def test_invalid_pagination(self):
        with self.assertRaises(HTTPError) as error:self.call('/api/items?offset=-1')
        self.assertEqual(error.exception.code,400)


if __name__=='__main__':unittest.main()
