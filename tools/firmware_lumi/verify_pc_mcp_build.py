"""Verify removal of board notebook, preserving every unrelated flash region."""
import argparse
import hashlib
import json
import struct
import sys
import zlib
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from prepare_spanish_status import layout,image_checksum


def partitions(data):
    result={}
    for offset in range(0,3072,32):
        row=data[offset:offset+32]
        magic=struct.unpack_from('<H',row)[0]
        if magic==0xEBEB:
            assert hashlib.md5(data[:offset]).digest()==row[16:32],'Partition MD5 mismatch'
            return result
        assert magic==0x50AA,'Invalid partition entry'
        _,kind,subtype,start,size,name,flags=struct.unpack('<HBBII16sI',row)
        label=name.rstrip(b'\0').decode('ascii')
        assert label not in result
        result[label]=(kind,subtype,start,size,flags)
    raise AssertionError('Missing partition MD5')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('build',type=Path)
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[2]
    previous=(root/'.build/layout-before-remove-local-notes-20261014.bin').read_bytes()
    assert len(previous)==0x8000
    table=(args.build/'partition_table/partition-table.bin').read_bytes()
    old,new=partitions(previous[:4096]),partitions(table)
    assert old.pop('lumi_notes')==(1,2,0x10000,0x10000,0)
    assert new==old,'An unrelated partition moved or changed'
    valid=[]
    for offset in (0x5000,0x6000):
        sequence=struct.unpack_from('<I',previous,offset)[0]
        state,crc=struct.unpack_from('<II',previous,offset+24)
        if sequence!=0xFFFFFFFF and state not in (3,4):
            assert zlib.crc32(previous[offset:offset+4],0xFFFFFFFF)==crc
            valid.append(sequence)
    assert valid and (max(valid)-1)%2==0,'Active OTA slot is not ota_0'
    image=(args.build/'xiaozhi.bin').read_bytes()
    assert len(image)<=old['ota_0'][3]
    assert struct.unpack_from('<H',image,12)[0]==9
    segments,end=layout(image)
    assert image_checksum(image,segments)==image[end-1]
    assert hashlib.sha256(image[:end]).digest()==image[end:]
    for marker in (b'Lumi touch: start chat',b'Lumi touch: stop chat',b'es-ES',b'self.audio_speaker.set_volume'):
        assert marker in image,marker
    for marker in (b'self.notes.create',b'self.notes.list',b'self.notes.get',b'self.notes.update',b'self.notes.delete',b'lumi_notes'):
        assert marker not in image,marker
    board=(root/'tools/firmware_lumi/esp32-s3-touch-amoled-2.16.cc').read_text(encoding='utf-8')
    assert 'PowerSaveTimer(-1, 60, -1)' in board
    config=(args.build.parent/'sdkconfig').read_text(encoding='utf-8')
    for setting in ('CONFIG_LANGUAGE_ES_ES=y','CONFIG_SPIRAM_MODE_OCT=y','CONFIG_ESPTOOLPY_FLASHSIZE_16MB=y'):
        assert setting in config
    target=root/'.build/application-lumi-pc-mcp-es-20261014.bin'
    target.write_bytes(image)
    (root/'.build/lumi-table-pc-mcp-20261014.bin').write_bytes(table)
    metadata={'sha256':hashlib.sha256(image).hexdigest(),'bytes':len(image),'application_offset':'0x20000','table_offset':'0x8000',
        'table_sha256':hashlib.sha256(table).hexdigest(),'notes_tools_removed':True,'notes_partition_removed':True,
        'unallocated_offset':'0x10000','unallocated_bytes':65536,'unrelated_partitions_unchanged':True,
        'installed':False,'backup':'.build/app-before-remove-local-notes-20261014.bin'}
    target.with_suffix('.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')
    print(json.dumps(metadata,indent=2))


if __name__=='__main__':main()
