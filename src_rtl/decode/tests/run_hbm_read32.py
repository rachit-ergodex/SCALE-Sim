"""Verilator/cocotb validation of the independent 32-port HBM read frontend."""
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import sys
from xml.etree import ElementTree
from cocotb_tools.runner import get_runner

HERE=Path(__file__).resolve().parents[1]

def main():
    sources=[HERE/'rtl/decode_hbm_read_port.sv',HERE/'rtl/decode_hbm_read32.sv']
    checked=sources+[HERE/'tests/test_hbm_read32.py',Path(__file__)]
    before={str(p.relative_to(HERE)):hashlib.sha256(p.read_bytes()).hexdigest() for p in checked}
    os.environ['PATH']=str(Path(sys.executable).parent)+os.pathsep+os.environ['PATH']
    build=HERE/'build/hbm_read32';runner=get_runner('verilator')
    runner.build(sources=sources,hdl_toplevel='decode_hbm_read32',build_dir=build,build_args=['-Wall'],clean=True,always=True)
    runner.test(hdl_toplevel='decode_hbm_read32',test_module='test_hbm_read32',test_dir=HERE/'tests',build_dir=build,results_xml=str(build/'results.xml'))
    root=ElementTree.parse(build/'results.xml').getroot()
    assert len(root.findall('.//testcase'))==1 and not root.findall('.//failure') and not root.findall('.//error')
    assert before=={str(p.relative_to(HERE)):hashlib.sha256(p.read_bytes()).hexdigest() for p in checked}
    report=dict(status='passed',scope='HBM-clock-domain read frontends, behavioral AXI target, no PHY/CDC or FPGA timing validation',ports=32,ids_per_port=64,total_request_capacity=2048,
        verified_reads=32*(256+160),source_sha256=before,cocotb=version('cocotb'),checks=['all 32 ports transfer simultaneously','256 consecutive full-rate response cycles','all 2048 credits occupied','random AR and output stalls','out-of-order response IDs','per-port fault isolation','RRESP and RLAST errors','reset recovery'])
    (HERE/'hbm_read_verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print('PASS all 32 HBM read ports')

if __name__=='__main__':main()
