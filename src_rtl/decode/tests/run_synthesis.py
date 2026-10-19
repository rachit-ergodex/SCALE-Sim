"""Generic synthesis sanity checks, not FPGA place-and-route or ASIC PPA."""
from collections import Counter
import json
from pathlib import Path
import subprocess

HERE=Path(__file__).resolve().parents[1]

def main():
    build=HERE/'build'/'synthesis';build.mkdir(parents=True,exist_ok=True)
    reports=[]
    for top in ('decode_os_core','decode_scratchpad','decode_bank_lifetimes','decode_hbm_map'):
        out=build/f'{top}.json';log=build/f'{top}.log'
        script=(f'read_verilog -sv {HERE}/rtl/{top}.sv; hierarchy -check -top {top}; '
                f'proc; opt; wreduce; opt; memory_dff; memory_collect; opt_clean; check -assert; stat; write_json {out}')
        with log.open('w') as stream:subprocess.run(['yosys','-Q','-p',script],check=True,stdout=stream,stderr=subprocess.STDOUT)
        module=json.loads(out.read_text())['modules'][top];cells=list(module['cells'].values())
        assert not any('latch' in cell['type'] for cell in cells),top
        row={'top':top,'status':'passed','cells':dict(Counter(cell['type'] for cell in cells))}
        if top=='decode_os_core':
            macs=[cell for cell in cells if cell['type']=='$mul' and
                int(cell['parameters']['A_WIDTH'],2)==8 and int(cell['parameters']['B_WIDTH'],2)==8]
            assert len(macs)==4*8
            assert all(int(cell['parameters']['A_SIGNED'],2) and int(cell['parameters']['B_SIGNED'],2) for cell in macs)
            row['signed_int8_multipliers']=len(macs)
        if top=='decode_scratchpad':
            memories=[cell for cell in cells if cell['type']=='$mem_v2'];assert len(memories)==1
            params=memories[0]['parameters']
            assert int(params['WIDTH'],2)==256 and int(params['SIZE'],2)==4096
            # Clocked writes are required; read output may retain its external
            # enable/reset register after generic memory_dff optimization.
            assert int(params['WR_CLK_ENABLE'],2)>0
            row['memory_bits']=256*4096
        reports.append(row)
    (build/'summary.json').write_text(json.dumps(reports,indent=2)+'\n')
    print('PASS four generic synthesis checks; 32 signed INT8 multipliers; retained scratch SRAM')

if __name__=='__main__':main()
