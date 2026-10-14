import json
import shutil
import subprocess
import sys
from pathlib import Path


def test_new_config_requires_identity_and_uses_pc_mcp(tmp_path):
    script=tmp_path/'configure.py'
    shutil.copyfile(Path(__file__).with_name('configure.py'),script)
    missing=subprocess.run([sys.executable,str(script)],capture_output=True)
    assert missing.returncode==2
    assert not script.with_name('local_config.json').exists()
    created=subprocess.run([sys.executable,str(script),'--device-id','02:00:00:00:00:01','--pc-ip','127.0.0.1'],capture_output=True)
    assert created.returncode==0
    cfg=json.loads(script.with_name('local_config.json').read_text())
    assert cfg['device_id']=='02:00:00:00:00:01'
    assert cfg['notebook_provider']=='pc_mcp'
    assert cfg['pc_ip']=='127.0.0.1'
    assert len(cfg['token'])>=32
    assert cfg['token'].encode() not in created.stdout


def test_existing_config_is_never_overwritten(tmp_path):
    script=tmp_path/'configure.py'
    shutil.copyfile(Path(__file__).with_name('configure.py'),script)
    private=script.with_name('local_config.json')
    original=b'{"token":"sentinel"}'
    private.write_bytes(original)
    result=subprocess.run([sys.executable,str(script)],capture_output=True)
    assert result.returncode==0
    assert private.read_bytes()==original
