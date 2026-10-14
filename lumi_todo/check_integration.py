"""Read-only acceptance through the active voice registry, MCP and visual API."""
import argparse
import json
import sys
import time
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError

from board_migration import content_hash


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--migration',type=Path,required=True)
    parser.add_argument('--report',type=Path,required=True)
    parser.add_argument('--wait',type=float,default=45)
    parser.add_argument('--task-status',choices=['pending','completed'],default='pending')
    parser.add_argument('--task-query',required=True,help='Texto de una tarea técnica creada para esta verificación local.')
    args=parser.parse_args()
    sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'xiaozhi_openai_bridge'))
    from config import settings
    cfg=settings()
    def voice(name,arguments):
        request=Request(f"http://{cfg['pc_ip']}:{cfg['port']}/lumi/tool",data=json.dumps({'name':name,'arguments':arguments}).encode(),
            headers={'authorization':'Bearer '+cfg['token'],'content-type':'application/json'})
        deadline=time.monotonic()+args.wait
        while True:
            try:
                with urlopen(request,timeout=15) as response:result=json.load(response)
                break
            except HTTPError as error:
                if error.code!=409 or time.monotonic()>deadline:raise
                time.sleep(.5)
        if result.get('isError'):raise RuntimeError('La ruta de voz no confirmó la consulta MCP.')
        return result['structuredContent']
    migration=json.loads(args.migration.read_text())
    verified=0
    for entry in migration['mapping']:
        item=voice('notes_get',{'id':entry['new_id']})['item']
        with urlopen('http://127.0.0.1:8765/api/items/'+entry['new_id'],timeout=5) as response:visual=json.load(response)
        assert item==visual,'Voice/visual mismatch'
        assert content_hash(item['title'],item['text'])==entry['sha256'],'Migration mismatch'
        verified+=1
    tasks=voice('tasks_list',{'query':args.task_query,'status':args.task_status})
    task_matches=0
    for summary in tasks['items']:
        item=voice('tasks_get',{'id':summary['id']})['item']
        with urlopen('http://127.0.0.1:8765/api/items/'+summary['id'],timeout=5) as response:visual=json.load(response)
        assert item==visual and item['status']==args.task_status,'Task state mismatch'
        task_matches+=1
    report={'active_voice_registry':True,'mcp_notes_match_visual':verified,'migration_hashes_match':True,
        'dictated_task_visible':any(item['source']=='lumi' for item in tasks['items']),
        'task_status':args.task_status,'mcp_tasks_match_visual':task_matches,
        'provider':'pc_mcp','read_only_check':True}
    args.report.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report))


if __name__=='__main__':main()
