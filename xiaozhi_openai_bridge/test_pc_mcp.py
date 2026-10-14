import asyncio
import json
import pytest
import server
from test_bridge import Device,API,CFG
from live_bridge import live_session_config
from fastapi.testclient import TestClient


@pytest.mark.asyncio
async def test_pc_catalog_and_routing_excludes_board_notes(monkeypatch):
    class Provider:
        ready=asyncio.Event()
        tools={'notes_create':{'name':'notes_create','inputSchema':{'type':'object','properties':{'title':{'type':'string'},'request_id':{'type':'string'}},'required':['title','request_id']}}}
        calls=[]
        async def call(self,name,args):
            self.calls.append((name,args))
            return {'isError':False,'structuredContent':{'ok':True}}
    provider=Provider();provider.ready.set()
    monkeypatch.setattr(server,'pc_provider',provider)
    device,api=Device(),API()
    bridge=server.Bridge(device,api,{**CFG,'notebook_provider':'pc_mcp'})
    async def rpc(method,params):
        if method=='tools/list':return {'tools':[{'name':name,'inputSchema':{'type':'object','properties':{}}} for name in server.ALLOWED]}
        return {}
    bridge.rpc=rpc
    await bridge.discover()
    assert 'self_notes_create' not in bridge.tools
    assert 'self.notes.create' in bridge.board_tools
    assert 'self_audio_speaker_set_volume' in bridge.tools
    assert 'request_id' not in bridge.tools['notes_create']['inputSchema']['properties']
    call={'type':'function_call','name':'notes_create','arguments':json.dumps({'title':'Comprar pan'}),'call_id':'call-1'}
    await bridge.execute_tools({'output':[call]})
    await bridge.execute_tools({'output':[call]})
    assert provider.calls[0][0]=='notes_create'
    assert provider.calls[0][1]['request_id']==provider.calls[1][1]['request_id']
    assert 'PC' in live_session_config(bridge.cfg)['instructions']


@pytest.mark.asyncio
async def test_provider_failure_does_not_fallback_to_board(monkeypatch):
    monkeypatch.setattr(server,'pc_provider',None)
    bridge=server.Bridge(Device(),API(),{**CFG,'notebook_provider':'pc_mcp'})
    bridge.tools={'notes_create':{'name':'notes_create'}}
    bridge.tool_providers={'notes_create':'pc_mcp'}
    async def forbidden_rpc(*args):raise AssertionError('No board fallback')
    bridge.rpc=forbidden_rpc
    await bridge.execute_tools({'output':[{'type':'function_call','name':'notes_create','arguments':'{}','call_id':'x'}]})
    output=json.loads(bridge.api.sent[0]['item']['output'])
    assert output['isError'] is True
    assert bridge.api.sent[-1]['type']=='response.create'


def test_technical_routes_auth_and_board_writes_disabled(monkeypatch):
    cfg={**CFG,'notebook_provider':'pc_mcp'}
    monkeypatch.setattr(server,'settings',lambda:cfg)
    calls=[]
    class ActiveBridge:
        tools={'notes_get':{}}
        board_tools={'self.notes.list':{},'self.notes.get':{},'self.notes.create':{}}
        async def dispatch_tool(self,name,arguments,call_id):
            calls.append(name)
            return {'isError':False,'structuredContent':{'ok':True}}
        async def rpc(self,method,params):
            calls.append(params['name'])
            return {'isError':False}
    monkeypatch.setattr(server,'active',{CFG['device_id']:{'bridge':ActiveBridge()}})
    client=TestClient(server.app)
    headers={'authorization':'Bearer '+CFG['token']}
    payload={'name':'notes_get','arguments':{'id':'real-id'}}
    assert client.post('/lumi/tool',json=payload).status_code==403
    assert client.post('/lumi/tool',headers=headers,json={**payload,'request_id':[]}).status_code==400
    assert client.post('/lumi/tool',headers=headers,json=payload).json()['isError'] is False
    assert client.post('/notebook/tool',headers=headers,json={'name':'self.notes.create','arguments':{}}).status_code==409
    assert client.post('/notebook/tool',headers=headers,json={'name':'self.notes.list','arguments':{}}).json()['isError'] is False
    assert calls==['notes_get','self.notes.list']
