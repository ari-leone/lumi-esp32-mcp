import asyncio
import json
import os
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch
from pathlib import Path

from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client
from board_migration import content_hash,import_snapshot
from service import Store,AppError


class McpTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_stdio_shared_store_and_errors(self):
        with tempfile.TemporaryDirectory() as folder,open(os.devnull,'w') as errlog:
            params=StdioServerParameters(command=sys.executable,args=[str(Path(__file__).parent/'mcp_server.py'),'--data-dir',folder])
            async with stdio_client(params,errlog=errlog) as (read,write),ClientSession(read,write) as client:
                initialized=await client.initialize()
                self.assertEqual(initialized.serverInfo.name,'lumi-notas-tareas')
                self.assertEqual(len((await client.list_tools()).tools),12)
                async def call(name,args):
                    return await client.call_tool(name,args)
                payload={'title':'Reunión con café','text':'Nota técnica','request_id':str(uuid.uuid4())}
                result=await call('notes_create',payload)
                self.assertFalse(result.isError)
                item=result.structuredContent['item']
                store=Store(Path(folder)/'lumi.sqlite3')
                self.assertEqual(store.get(item['id'])['source'],'lumi')
                replay=await call('notes_create',payload)
                self.assertEqual(replay.structuredContent['item']['id'],item['id'])
                listing=await call('notes_list',{'query':'CAFÉ'})
                self.assertEqual(listing.structuredContent['total'],1)
                self.assertNotIn('text',listing.structuredContent['items'][0])
                edited=store.mutate('update',{'title':'Edición desde PC','text':'Nuevo texto','expected_version':1,'request_id':str(uuid.uuid4())},item['id'])
                get=await call('notes_get',{'id':item['id']})
                self.assertEqual(get.structuredContent['item']['text'],'Nuevo texto')
                conflict=await call('notes_update',{'id':item['id'],'title':'Viejo','text':'','expected_version':1,'request_id':str(uuid.uuid4())})
                self.assertTrue(conflict.isError)
                self.assertEqual(conflict.structuredContent['error'],'conflict')
                invalid=await call('notes_get',{'id':item['id'],'unexpected':1})
                self.assertTrue(invalid.isError)
                task=(await call('tasks_create',{'title':'Comprar pan','due_date':'2026-10-15','request_id':str(uuid.uuid4())})).structuredContent['item']
                wrong=await call('notes_get',{'id':task['id']})
                self.assertTrue(wrong.isError)
                completed=(await call('tasks_complete',{'id':task['id'],'expected_version':task['version'],'request_id':str(uuid.uuid4())})).structuredContent['item']
                reopened=(await call('tasks_reopen',{'id':task['id'],'expected_version':completed['version'],'request_id':str(uuid.uuid4())})).structuredContent['item']
                self.assertEqual(reopened['id'],task['id'])
                self.assertEqual(reopened['status'],'pending')
                deleted=await call('notes_delete',{'id':edited['id'],'expected_version':edited['version'],'request_id':str(uuid.uuid4())})
                self.assertFalse(deleted.isError)
                self.assertEqual(store.counts()['trash'],1)

    async def test_provider_owner_lifecycle(self):
        sys.path.insert(0,str(Path(__file__).parent.parent/'xiaozhi_openai_bridge'))
        from mcp_provider import PcMcpProvider
        with tempfile.TemporaryDirectory() as folder:
            provider=PcMcpProvider({'notebook_data_dir':folder})
            await provider.start()
            try:
                await asyncio.wait_for(provider.ready.wait(),15)
                result=await provider.call('tasks_list',{})
                self.assertFalse(result['isError'])
                self.assertEqual(result['structuredContent']['total'],0)
            finally:await provider.close()
            self.assertFalse(provider.ready.is_set())
            with self.assertRaises(RuntimeError):await provider.call('tasks_list',{})

    async def test_provider_reconnect_does_not_repeat_uncertain_write(self):
        sys.path.insert(0,str(Path(__file__).parent.parent/'xiaozhi_openai_bridge'))
        from mcp_provider import PcMcpProvider
        original=ClientSession.call_tool
        interrupted=False
        async def lost_confirmation(session,name,*args,**kwargs):
            nonlocal interrupted
            result=await original(session,name,*args,**kwargs)
            if name=='notes_create' and not interrupted:
                interrupted=True
                raise RuntimeError('Simulated lost confirmation after commit')
            return result
        with tempfile.TemporaryDirectory() as folder,patch.object(ClientSession,'call_tool',lost_confirmation):
            provider=PcMcpProvider({'notebook_data_dir':folder})
            await provider.start()
            payload={'title':'No duplicar','request_id':'stable-write'}
            try:
                await asyncio.wait_for(provider.ready.wait(),15)
                with self.assertRaises(RuntimeError):await provider.call('notes_create',payload)
                await asyncio.wait_for(provider.ready.wait(),15)
                self.assertEqual(Store(Path(folder)/'lumi.sqlite3').counts()['notes'],1)
                replay=await provider.call('notes_create',payload)
                self.assertFalse(replay['isError'])
                self.assertEqual(Store(Path(folder)/'lumi.sqlite3').counts()['notes'],1)
            finally:await provider.close()


class MigrationTests(unittest.TestCase):
    def test_repeat_import_and_conflict_rollback(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Store(Path(folder)/'lumi.sqlite3')
            note={'id':1,'title':'Comprar pan','text':'Café y mañana'}
            note['sha256']=content_hash(note['title'],note['text'])
            snapshot={'format':'lumi-board-snapshot','device_id':'test-board','notes':[note]}
            self.assertEqual(import_snapshot(store,snapshot)['imported'],1)
            self.assertEqual(import_snapshot(store,snapshot)['skipped'],1)
            new={**note,'id':2}
            changed={**note,'text':'Otra versión','sha256':content_hash(note['title'],'Otra versión')}
            with self.assertRaises(AppError):import_snapshot(store,{**snapshot,'notes':[new,changed]})
            self.assertEqual(store.counts()['notes'],1)
            item=store.list('notes')['items'][0]
            self.assertEqual(item['text'],note['text'])


if __name__=='__main__':unittest.main()
