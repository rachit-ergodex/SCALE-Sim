"""Generic synthesis sanity checks, not FPGA place-and-route or ASIC PPA."""
from collections import Counter
import json
from pathlib import Path
import subprocess

HERE=Path(__file__).resolve().parents[1]

def main():
    build=HERE/'build'/'synthesis';build.mkdir(parents=True,exist_ok=True)
    reports=[]
    for top in ('decode_os_core','decode_scratchpad','decode_bank_lifetimes','decode_hbm_map','decode_async_fifo','decode_hbm_read_bridge32'):
        out=build/f'{top}.json';log=build/f'{top}.log'
        sources=[HERE/'rtl'/f'{top}.sv']
        if top=='decode_hbm_read_bridge32':
            sources += [HERE/'rtl'/f'{name}.sv' for name in ('decode_async_fifo','decode_hbm_read_port','decode_hbm_read_bridge')]
        script=(f"read_verilog -sv {' '.join(str(p) for p in sources)}; hierarchy -check -top {top}; "
                f'proc; opt; wreduce; opt; memory_dff; memory_collect; opt_clean; check -assert; stat; write_json {out}')
        with log.open('w') as stream:subprocess.run(['yosys','-Q','-p',script],check=True,stdout=stream,stderr=subprocess.STDOUT)
        modules=json.loads(out.read_text())['modules'];module=modules[top];cells=list(module['cells'].values())
        assert not any('latch' in cell['type'] for mod in modules.values() for cell in mod['cells'].values()),top
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
        if top=='decode_async_fifo':
            memories=[cell for cell in cells if cell['type']=='$mem_v2'];assert len(memories)==1
            params=memories[0]['parameters']
            assert int(params['WIDTH'],2)==64 and int(params['SIZE'],2)==16
            assert int(params['WR_CLK_ENABLE'],2)==1
            sync=[net for net in module['netnames'].values() if net.get('attributes',{}).get('ASYNC_REG')=='TRUE']
            assert len(sync)==4
            row['memory_bits']=64*16;row['gray_synchronizer_registers']=4
        if top=='decode_hbm_read_bridge32':
            assert len(cells)==32
            assert all('decode_hbm_read_bridge' in cell['type'] for cell in cells)
            row['independent_port_bridges']=32
        reports.append(row)
    (build/'summary.json').write_text(json.dumps(reports,indent=2)+'\n')
    print('PASS six generic synthesis checks; signed INT8 MACs, SRAM, async FIFO and 32 independent bridges')

if __name__=='__main__':main()
