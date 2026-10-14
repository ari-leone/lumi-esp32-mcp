"""One stdio owner task, independent from voice sessions; no cross-task exit stacks."""
import asyncio
import logging
import os
import sys
from datetime import timedelta
from pathlib import Path

log=logging.getLogger('uvicorn.error')
PC_TOOL_NAMES={prefix+'_'+action for prefix in ('notes','tasks') for action in
               (['create','list','get','update','delete']+(['complete','reopen'] if prefix=='tasks' else []))}


class PcMcpProvider:
    def __init__(self,cfg):
        self.cfg=cfg
        self.tools={}
        self.ready=asyncio.Event()
        self.queue=asyncio.Queue(maxsize=32)
        self.task=None

    async def start(self):
        self.task=asyncio.create_task(self.worker())

    async def close(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task,return_exceptions=True)

    async def call(self,name,arguments):
        if name not in PC_TOOL_NAMES or not self.ready.is_set():
            raise RuntimeError('El bloc del PC no está disponible. No se ha confirmado la operación.')
        future=asyncio.get_running_loop().create_future()
        try:
            self.queue.put_nowait((name,arguments,future))
            return await asyncio.wait_for(future,12)
        except asyncio.QueueFull:
            raise RuntimeError('El bloc del PC está ocupado. No se ha confirmado la operación.')

    async def worker(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        script=Path(__file__).resolve().parent.parent/'lumi_todo'/'mcp_server.py'
        data_dir=self.cfg.get('notebook_data_dir') or str(Path(os.environ['LOCALAPPDATA'])/'LumiNotes')
        # Never pass the bridge's API credential to the notebook child.
        child_env={key:os.environ[key] for key in ('SYSTEMROOT','WINDIR','COMSPEC','TEMP','TMP','PATH','LOCALAPPDATA','USERPROFILE') if key in os.environ}
        child_env.update(PYTHONIOENCODING='utf-8',PYTHONUNBUFFERED='1')
        params=StdioServerParameters(command=sys.executable,args=[str(script),'--data-dir',data_dir],env=child_env)
        current=None
        while True:
            try:
                # SDK diagnostics can include validation payloads. Keep them out of voice logs.
                with open(os.devnull,'w') as errlog:
                    async with stdio_client(params,errlog=errlog) as (read,write):
                        async with ClientSession(read,write,read_timeout_seconds=timedelta(seconds=10)) as session:
                            await session.initialize()
                            response=await session.list_tools()
                            self.tools={t.name:t.model_dump(exclude_none=True) for t in response.tools if t.name in PC_TOOL_NAMES}
                            if set(self.tools)!=PC_TOOL_NAMES:
                                raise RuntimeError('Catálogo MCP incompleto')
                            self.ready.set()
                            log.info('Bloc PC MCP disponible: %s herramientas',len(self.tools))
                            while True:
                                try:
                                    current=await asyncio.wait_for(self.queue.get(),5)
                                except TimeoutError:
                                    await session.send_ping()
                                    continue
                                name,arguments,future=current
                                if future.cancelled():
                                    current=None
                                    continue
                                result=await session.call_tool(name,arguments)
                                if not future.done():
                                    future.set_result(result.model_dump(exclude_none=True))
                                current=None
            except asyncio.CancelledError:
                raise
            except Exception:
                log.warning('Bloc PC MCP no disponible; se reintentará sin repetir escrituras')
            finally:
                self.ready.clear()
                if current and not current[2].done():
                    current[2].set_exception(RuntimeError('El bloc del PC no confirmó la operación.'))
                current=None
                while not self.queue.empty():
                    _,_,future=self.queue.get_nowait()
                    if not future.done():
                        future.set_exception(RuntimeError('El bloc del PC no está disponible.'))
            await asyncio.sleep(3)
