"""Run independent native timings for matched ASIC/F2 partition configurations."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from run import build

HERE=Path(__file__).resolve().parent
DEFAULTS=['decode_4arrays_only','decode_asic_4arrays','decode_asic_8arrays',
          'decode_asic_32x64','decode_f2_4arrays','decode_f2_8arrays',
          'decode_f2_16arrays','decode_f2_64x64']

def main():
    parser=argparse.ArgumentParser();parser.add_argument('profiles',nargs='*',default=DEFAULTS)
    parser.add_argument('--workers',type=int,default=2);args=parser.parse_args()
    assert args.workers>0
    for name in args.profiles:
        subprocess.run([sys.executable,str(HERE/'run.py'),'--config',str(HERE/'configs'/f'{name}.json'),'--prepare-only'],check=True)
    binary=build()
    def run(name):
        folder=HERE/'build'/name;cfg=json.loads((folder/'configuration.json').read_text())
        with (folder/'ramulator.log').open('w') as log:
            subprocess.run([str(binary),str(folder/'hbm2.json'),str(folder/'commands.txt'),str(folder/'timing.csv'),
                str(cfg['core_hz']),'16','10000000',str(cfg['max_inflight_requests']),
                str(int(cfg['hbm_address_mapping']=='pc_bankgroup'))],check=True,stdout=log,stderr=subprocess.STDOUT)
        p=folder/'execution.json';execution=json.loads(p.read_text())
        execution.update(status='completed',timing_sha256=hashlib.sha256((folder/'timing.csv').read_bytes()).hexdigest())
        p.write_text(json.dumps(execution,indent=2)+'\n')
        subprocess.run([sys.executable,str(HERE/'run.py'),'--out',str(folder),'--summarize-only'],check=True)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:list(pool.map(run,args.profiles))

if __name__=='__main__':main()
