"""Read-only board snapshot and atomic, repeatable import. No voice data sent to APIs."""
import argparse
import hashlib
import json
import os
import sys
import time
import uuid
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError

from service import AppError,Store,now


def content_hash(title,text):
    return hashlib.sha256(json.dumps([title,text],ensure_ascii=False,separators=(',',':')).encode('utf-8')).hexdigest()


def board_snapshot(cfg):
    deadline=time.monotonic()+45
    def call(action,args):
        request=Request(f"http://{cfg['pc_ip']}:{cfg['port']}/notebook/tool",data=json.dumps({'name':'self.notes.'+action,'arguments':args}).encode(),
            headers={'authorization':'Bearer '+cfg['token'],'content-type':'application/json'})
        while True:
            try:
                with urlopen(request,timeout=12) as response:result=json.load(response)
                break
            except HTTPError as error:
                if error.code!=409 or time.monotonic()>deadline:
                    raise
                time.sleep(.5)
        if result.get('isError'):
            raise AppError('board_error','La placa no confirmó la lectura.')
        return json.loads(next(block['text'] for block in result['content'] if block['type']=='text'))
    before=call('list',{'query':''})['notes']
    notes=[]
    for entry in before:
        note=call('get',{'id':entry['id']})
        notes.append({**note,'sha256':content_hash(note['title'],note['text'])})
    after=call('list',{'query':''})['notes']
    if before!=after:
        raise AppError('conflict','El bloc cambió durante la extracción. Repite la lectura antes de importar.')
    # Some firmware list implementations return summaries; re-read each record to detect edits.
    for note in notes:
        current=call('get',{'id':note['id']})
        if content_hash(current['title'],current['text'])!=note['sha256']:
            raise AppError('conflict','Una nota cambió durante la extracción.')
    return {'format':'lumi-board-snapshot','device_id':cfg['device_id'],'exported_at':now(),'notes':notes}


def import_snapshot(store,snapshot):
    if not isinstance(snapshot,dict) or snapshot.get('format')!='lumi-board-snapshot' or not isinstance(snapshot.get('device_id'),str):
        raise AppError('validation','Exportación de placa no válida.')
    notes=snapshot.get('notes')
    if not isinstance(notes,list) or len(notes)>20:
        raise AppError('validation','Inventario de notas no válido.')
    imported,skipped,mapping=0,0,[]
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('CREATE TABLE IF NOT EXISTS board_imports (device_id TEXT NOT NULL,old_id INTEGER NOT NULL,new_id TEXT NOT NULL REFERENCES items(id),sha256 TEXT NOT NULL,imported_at TEXT NOT NULL,PRIMARY KEY(device_id,old_id))')
        seen=set()
        for note in notes:
            if not isinstance(note,dict) or type(note.get('id')) is not int or note['id'] in seen:
                raise AppError('validation','Identificador antiguo no válido o duplicado.')
            seen.add(note['id'])
            store.validate(note)
            digest=content_hash(note['title'],note['text'])
            if digest!=note.get('sha256'):
                raise AppError('validation','El contenido no coincide con su hash.')
            old=db.execute('SELECT * FROM board_imports WHERE device_id=? AND old_id=?',(snapshot['device_id'],note['id'])).fetchone()
            if old:
                if old['sha256']!=digest:
                    raise AppError('conflict','Una nota de la placa cambió después de importarse. No se sobrescribió el PC.')
                item=store.get(old['new_id'],db)
                # Allow repeat import only if original contents still agree.
                if content_hash(item['title'],item['text'])!=digest:
                    raise AppError('conflict','La nota importada cambió en el PC. Se requiere reconciliación.')
                new_id=old['new_id'];skipped+=1
            else:
                new_id=str(uuid.uuid4());stamp=now()
                db.execute('INSERT INTO items(id,kind,title,text,created_at,updated_at,source) VALUES(?,?,?,?,?,?,?)',
                    (new_id,'note',note['title'],note['text'],stamp,stamp,'import'))
                db.execute('INSERT INTO board_imports VALUES(?,?,?,?,?)',(snapshot['device_id'],note['id'],new_id,digest,stamp))
                imported+=1
            actual=store.get(new_id,db)
            if actual['title']!=note['title'] or actual['text']!=note['text']:
                raise AppError('conflict','Verificación del contenido fallida.')
            mapping.append({'old_id':note['id'],'new_id':new_id,'sha256':digest})
    return {'imported':imported,'skipped':skipped,'count':len(notes),'mapping':mapping,'verified':True}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['export','import'])
    parser.add_argument('--snapshot',type=Path,required=True)
    parser.add_argument('--data-dir',type=Path,default=Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'LumiNotes')
    args=parser.parse_args()
    if args.action=='export':
        sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'xiaozhi_openai_bridge'))
        from config import settings
        snapshot=board_snapshot(settings())
        args.snapshot.parent.mkdir(parents=True,exist_ok=True)
        # Avoid replacing an earlier private snapshot.
        with args.snapshot.open('x',encoding='utf-8') as file:json.dump(snapshot,file,ensure_ascii=False,indent=2)
        print(json.dumps({'exported':len(snapshot['notes']),'consistent':True}))
    else:
        store=Store(args.data_dir/'lumi.sqlite3')
        store.backup()
        result=import_snapshot(store,json.loads(args.snapshot.read_text(encoding='utf-8')))
        with args.snapshot.with_suffix('.migration.json').open('w',encoding='utf-8') as file:json.dump(result,file,indent=2)
        print(json.dumps({k:v for k,v in result.items() if k!='mapping'}))


if __name__=='__main__':main()
