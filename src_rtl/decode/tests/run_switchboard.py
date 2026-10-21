"""Real Switchboard shared-memory queues -> C++ adapter -> Verilator RTL."""
import json
import math
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import time

import numpy as np
import switchboard
from switchboard import PySbPacket,PySbTx,PySbRx

HERE=Path(__file__).resolve().parents[1]

def main():
    build=HERE/'build'/'switchboard';build.mkdir(parents=True,exist_ok=True)
    include=Path(switchboard.__file__).parent/'cpp'
    subprocess.run(['verilator','--cc','--exe','--build','-j','4','-Wall','--top-module','decode_os_core',
        '--Mdir',str(build),'-GPARTITIONS=4','-GCOLS=8','-CFLAGS',f'-std=c++17 -I{include}',
        str(HERE/'rtl'/'decode_os_core.sv'),str(HERE/'switchboard'/'main.cpp')],check=True)
    rng=np.random.default_rng(991);cases=0
    with tempfile.TemporaryDirectory(prefix='decode-sb-') as tmp:
        to_rtl=str(Path(tmp)/'to.q');from_rtl=str(Path(tmp)/'from.q')
        tx=PySbTx(to_rtl,fresh=True);rx=PySbRx(from_rtl,fresh=True)
        process=subprocess.Popen([str(build/'Vdecode_os_core'),to_rtl,from_rtl])
        def send(op,payload):
            data=np.zeros(52,dtype=np.uint8);data[:len(payload)]=np.frombuffer(payload,dtype=np.uint8)
            packet=PySbPacket(destination=op,data=data,flags=1);deadline=time.monotonic()+30
            while not tx.send(packet,blocking=False):
                assert process.poll() is None and time.monotonic()<deadline,'Switchboard TX timeout'
                time.sleep(.001)
        def recv():
            deadline=time.monotonic()+30
            while True:
                packet=rx.recv(blocking=False)
                if packet is not None:return packet
                assert process.poll() is None and time.monotonic()<deadline,'Switchboard RX timeout'
                time.sleep(.001)
        def load(op,data):
            for offset in range(0,len(data),44):
                chunk=data[offset:offset+44];send(op,struct.pack('<II',offset,len(chunk))+chunk)
        try:
            for m,k,n in [(1,1,1),(4,17,8),(3,13,17),(1,513,32),(4,23,7),(2,41,31)]:
                a=rng.integers(-128,128,(m,k),dtype=np.int8);b=rng.integers(-128,128,(k,n),dtype=np.int8)
                load(1,a.tobytes());load(2,b.tobytes())
                seed=rng.integers(-(1<<31),(1<<31),(m,n),dtype=np.int32)
                flat=seed.ravel()
                for offset in range(0,flat.size,11):
                    chunk=flat[offset:offset+11];send(3,struct.pack('<II',offset,len(chunk))+chunk.astype('<i4').tobytes())
                for flags in range(4):
                    send(4,struct.pack('<IIIII',m,k,n,flags,42+cases))
                    result=np.zeros(m*n,dtype=np.int32);seen=set()
                    while True:
                        packet=recv();words=np.frombuffer(packet.data.tobytes(),dtype='<u4')
                        if packet.destination==1:
                            workers=min(m,4//math.ceil(n/8)) if flags&1 else 1
                            assert words[0]==math.ceil(m/workers)*(k+7)
                            assert words[1]==words[0]+words[2] and words[2]>0
                            break
                        assert packet.destination==0
                        offset,length=map(int,words[:2]);assert 0<length<=11 and offset+length<=m*n
                        for i in range(offset,offset+length):assert i not in seen;seen.add(i)
                        result[offset:offset+length]=words[2:2+length].view(np.int32)
                    golden=a.astype(np.int64)@b.astype(np.int64)
                    if flags&2:golden+=seed.astype(np.int64)
                    np.testing.assert_array_equal(result.reshape(m,n),golden.astype(np.int32))
                    assert len(seen)==m*n;cases+=1
            send(0,b'');assert process.wait(timeout=10)==0
        finally:
            if process.poll() is None:process.kill();process.wait()
    (build/'summary.json').write_text(json.dumps({'status':'passed','cases':cases,'transport':'Switchboard shared-memory queues','simulator':'Verilator','reference':'independent NumPy INT64, explicit INT32 wrap'},indent=2)+'\n')
    print(f'PASS {cases} Switchboard/Verilator GEMMs')

if __name__=='__main__':main()
