"""Native streaming transport measurement, independent of model decode timing."""
import argparse
import csv
import hashlib
import json
import subprocess
from pathlib import Path
from run import build
from experiments.gemma3_1b_int8.hbm2.f2_config import make_f2_config

HERE=Path(__file__).resolve().parent

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--skip-build',action='store_true')
    args=parser.parse_args()
    binary=HERE/'build/runner' if args.skip_build else build()
    folder=HERE/'build/bandwidth_study';folder.mkdir(exist_ok=True)
    size=64*1024**2;commands=folder/'commands.txt'
    commands.write_text(f'0 0 stream R 0 {size} 1 0\n')
    rows=[]
    for name,window,queue,hz,mapping in [('linear512',512,32,10**9,False),
        ('interleaved512',512,32,10**9,True),('interleaved2048',2048,128,10**9,True),
        ('f2_interleaved2048',2048,128,250000000,True)]:
        config,profile=make_f2_config(16)
        for controller in config['memory_system']['controllers']:
            controller['read_buffer_size']=queue;controller['write_buffer_size']=queue
        cfg=folder/f'{name}.json';cfg.write_text(json.dumps(config))
        timing=folder/f'{name}.csv'
        subprocess.run([str(binary),str(cfg),str(commands),str(timing),str(hz),'16','100',str(window),str(int(mapping))],check=True)
        with timing.open() as stream:row=next(csv.DictReader(stream))
        assert int(row['reads'])*32==size and int(row['writes'])==0
        bandwidth=size*hz/int(row['end_core'])/1e9
        rows.append(dict(name=name,GB_per_s=bandwidth,peak_percent=bandwidth/profile['nominal_peak_GB_s']*100,
                         window=window,read_queue=queue,core_hz=hz,interleaved=mapping,
                         config_sha256=hashlib.sha256(cfg.read_bytes()).hexdigest(),
                         timing_sha256=hashlib.sha256(timing.read_bytes()).hexdigest()))
    result=dict(classification='Read-only HBM streaming transport microbenchmark; no compute or SRAM capacity constraint',
                bytes=size,results=rows,native_binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
                sources={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (HERE/'runner.cpp',HERE/'address_map.h',Path(__file__))})
    (folder/'results.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(rows,indent=2))

if __name__=='__main__':main()
