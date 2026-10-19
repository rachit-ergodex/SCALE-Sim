"""Retained directed HBM protocol suite; pass --rtl-dir for an external tree."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from xml.etree import ElementTree
from cocotb_tools.runner import get_runner

HERE=Path(__file__).resolve().parent
parser=argparse.ArgumentParser()
parser.add_argument('--rtl-dir',type=Path,default=HERE.parent/'rtl')
parser.add_argument('--build-dir',type=Path,default=HERE.parent/'build/hbm_directed')
parser.add_argument('--report',type=Path,default=HERE.parent/'hbm_directed_verification.json')
args=parser.parse_args()
os.environ['PATH']=str(Path(sys.executable).parent)+os.pathsep+os.environ['PATH']
sources=[args.rtl_dir/name for name in ('decode_async_fifo.sv','decode_hbm_read_port.sv','decode_hbm_read_bridge.sv')]
checked={f'rtl/{p.name}':p for p in sources}
checked.update({f'tests/{name}':HERE/name for name in ('test_hbm_directed_port.py','test_hbm_directed_bridge.py','run_hbm_directed.py')})
def hashes():return {name:hashlib.sha256(path.read_bytes()).hexdigest() for name,path in checked.items()}
before=hashes();cases=[]
for top,module,params in [
    ('decode_hbm_read_port','test_hbm_directed_port',{'PORT':31}),
    ('decode_hbm_read_bridge','test_hbm_directed_bridge',{'PORT':31,'FIFO_DEPTH':4}),
]:
    build=args.build_dir/top
    runner=get_runner('verilator')
    runner.build(sources=sources,hdl_toplevel=top,parameters=params,build_dir=build,build_args=['-Wall'],clean=True,always=True)
    runner.test(hdl_toplevel=top,test_module=module,test_dir=HERE,build_dir=build,results_xml=str(build/'results.xml'))
    root=ElementTree.parse(build/'results.xml').getroot()
    tests=root.findall('.//testcase')
    assert len(tests)==(6 if top=='decode_hbm_read_port' else 4) and not root.findall('.//failure') and not root.findall('.//error')
    cases.append(dict(top=top,parameters=params,status='passed',tests=[t.attrib['name'] for t in tests]))
    print('PASS',top,len(root.findall('.//testcase')),'directed tests')

assert before==hashes(),'Source changed while verification was running'
args.report.write_text(json.dumps(dict(status='passed',scope='Directed digital HBM protocol and CDC checks; no physical timing or vendor PHY claim',cases=cases,source_sha256=before),indent=2)+'\n')
