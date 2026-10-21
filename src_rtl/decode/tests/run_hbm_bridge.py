"""Verify 250/200 MHz return paths against approximately 450 MHz HBM."""
import hashlib
import json
import os
from pathlib import Path
import sys
from xml.etree import ElementTree
from cocotb_tools.runner import get_runner

HERE=Path(__file__).resolve().parents[1]

def main():
    sources=[HERE/'rtl'/name for name in ('decode_async_fifo.sv','decode_hbm_read_port.sv','decode_hbm_read_bridge.sv','decode_hbm_read_bridge32.sv')]
    checked=sources+[HERE/'tests/test_hbm_bridge.py',Path(__file__)]
    before={str(p.relative_to(HERE)):hashlib.sha256(p.read_bytes()).hexdigest() for p in checked}
    os.environ['PATH']=str(Path(sys.executable).parent)+os.pathsep+os.environ['PATH']
    cases=[]
    for ports,records,core_period,saturation in ((1,2,4000,False),(32,2,4000,False),(1,3,5000,False),(32,3,5000,False),(1,2,5000,True)):
        top='decode_hbm_read_bridge'+('32' if ports==32 else '')
        build=HERE/'build'/f'hbm_bridge{ports}_r{records}_p{core_period}';runner=get_runner('verilator')
        params={'FIFO_DEPTH':4 if ports==1 else 16,'RETURN_RECORDS':records}
        if ports==1:params['PORT']=31
        runner.build(sources=sources,hdl_toplevel=top,parameters=params,build_dir=build,build_args=['-Wall'],clean=True,always=True)
        runner.test(hdl_toplevel=top,test_module='test_hbm_bridge',test_dir=HERE/'tests',build_dir=build,results_xml=str(build/'results.xml'),extra_env={'HBM_PORTS':str(ports),'RETURN_RECORDS':str(records),'CORE_PERIOD_PS':str(core_period),'EXPECT_SATURATION':str(int(saturation)),'HBM_METRICS_PATH':str(build/'metrics.json')})
        root=ElementTree.parse(build/'results.xml').getroot()
        assert len(root.findall('.//testcase'))==1 and not root.findall('.//failure') and not root.findall('.//error')
        cases.append(dict(ports=ports,parameters=params,core_period_ps=core_period,hbm_period_ps=2222,expect_return_path_saturation=saturation,status='passed',metrics=json.loads((build/'metrics.json').read_text())))
    assert before=={str(p.relative_to(HERE)):hashlib.sha256(p.read_bytes()).hexdigest() for p in checked}
    report=dict(status='passed',scope='Digital CDC behavior only; no metastability, vendor PHY or physical timing claim',cases=cases,source_sha256=before)
    (HERE/'hbm_bridge_verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print('PASS 250 MHz legacy and 200 MHz three-record HBM clock crossings; two-record 200 MHz negative control saturates')

if __name__=='__main__':main()
