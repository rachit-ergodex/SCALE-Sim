"""Run reproducible decode RTL checks with Verilator and cocotb 2.x."""
import argparse
import json
import os
import sys
from pathlib import Path
from cocotb_tools.runner import get_runner

HERE=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--full',action='store_true');args=parser.parse_args()
    os.environ['PATH']=str(Path(sys.executable).parent)+os.pathsep+os.environ['PATH']
    cases=[('decode_os_core','test_os_core',{'PARTITIONS':4,'COLS':8})]
    if args.full:cases += [('decode_os_core','test_os_core',{'PARTITIONS':p,'COLS':64}) for p in (32,64)]
    cases += [('decode_scratchpad','test_scratchpad',{'DATA_WIDTH':256,'DEPTH':13}),
              ('decode_bank_lifetimes','test_bank_lifetimes',{}),('decode_hbm_map','test_hbm_map',{})]
    completed=[]
    for top,module,params in cases:
        tag=top+'_'+ '_'.join(f'{k}{v}' for k,v in params.items())
        build=HERE/'build'/tag
        runner=get_runner('verilator')
        runner.build(sources=[HERE/'rtl'/f'{top}.sv'],hdl_toplevel=top,parameters=params,
            build_dir=build,build_args=['-Wall'],always=True,clean=True)
        runner.test(hdl_toplevel=top,test_module=module,test_dir=HERE/'tests',build_dir=build,
            results_xml=str(build/'results.xml'),extra_env={'DECODE_PARTITIONS':str(params.get('PARTITIONS',4)),
                'DECODE_COLS':str(params.get('COLS',8))})
        # Runner only raises on failure under pytest. Check JUnit explicitly for CLI use.
        from xml.etree import ElementTree
        root=ElementTree.parse(build/'results.xml').getroot()
        assert len(root.findall('.//testcase'))>0
        assert not root.findall('.//failure') and not root.findall('.//error'),tag
        completed.append({'top':top,'parameters':params,'status':'passed'})
    (HERE/'build'/'cocotb_summary.json').write_text(json.dumps(completed,indent=2)+'\n')

if __name__=='__main__':main()
