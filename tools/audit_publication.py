"""Review eligible or staged Git files without displaying sensitive values."""
import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--staged',action='store_true')
    parser.add_argument('--git',default=shutil.which('git') or 'git')
    args=parser.parse_args()
    def git(*arguments):
        return subprocess.check_output([args.git,*arguments],cwd=ROOT)
    names=set(git('ls-files','--cached','-z').decode('utf-8').split('\0'))
    if not args.staged:names.update(git('ls-files','--others','--exclude-standard','-z').decode('utf-8').split('\0'))
    names.discard('')
    private_literals=[]
    local=ROOT/'xiaozhi_openai_bridge/local_config.json'
    if local.exists():
        cfg=json.loads(local.read_text(encoding='utf-8'))
        for key in ('api_key','token','device_id','pc_ip'):
            value=cfg.get(key)
            if isinstance(value,str) and len(value)>=7:private_literals.append(value.encode('utf-8'))
    data_dir=Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'LumiNotes'
    database=data_dir/'lumi.sqlite3'
    if database.exists():
        db=sqlite3.connect(database.as_uri()+'?mode=ro',uri=True)
        try:
            for title,content in db.execute('SELECT title,text FROM items'):
                for value in (title,content):
                    if isinstance(value,str) and len(value)>=12:private_literals.append(value.encode('utf-8'))
        finally:db.close()
    secret_patterns=[rb'sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,}',rb'gh[pousr]_[A-Za-z0-9]{20,}',
        rb'github_pat_[A-Za-z0-9_]{20,}',rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----']
    forbidden_extensions={'.bin','.elf','.map','.db','.sqlite','.sqlite3','.wav','.mp3','.mp4','.zip','.log','.pid'}
    findings=[]
    digest=hashlib.sha256()
    for name in sorted(names):
        path=Path(name)
        allowed=name in ('.gitignore','README.md','PUBLICACION_GITHUB.md','tools/audit_publication.py','tools/prepare_spanish_status.py') or name.startswith(('lumi_todo/','xiaozhi_openai_bridge/','tools/firmware_lumi/','assets/lumi/'))
        if not allowed or path.suffix.lower() in forbidden_extensions or path.name in ('local_config.json','secrets.h','.env') or path.name.startswith('VALIDACION') or any(part in ('__pycache__','.pytest_cache','backups','recordings') for part in path.parts):
            findings.append({'file':name,'reason':'private or non-source path'})
            continue
        content=git('show',':'+name) if args.staged else (ROOT/name).read_bytes()
        if any(value in content for value in private_literals):
            findings.append({'file':name,'reason':'matches a real local credential, identifier or notebook value'})
        if any(re.search(pattern,content) for pattern in secret_patterns):
            findings.append({'file':name,'reason':'credential or private-key pattern'})
        if re.search(rb'(?i)[a-z]:[\\/](?:users|usuarios)[\\/](?!public[\\/]|<)[a-z0-9_. -]+[\\/]',content):
            findings.append({'file':name,'reason':'personal absolute path'})
        digest.update(name.encode('utf-8')+b'\0'+hashlib.sha256(content).digest())
    print(json.dumps({'files_reviewed':len(names),'source_digest':digest.hexdigest(),'safe_to_publish':not findings,'findings':findings},ensure_ascii=False))
    raise SystemExit(bool(findings))


if __name__=='__main__':main()
