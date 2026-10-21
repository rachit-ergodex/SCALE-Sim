#!/usr/bin/env python3
"""Verify scan mapping and real-core stalls with Verilator/cocotb; no timing claim."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from xml.etree import ElementTree
from cocotb_tools.runner import get_runner

HERE=Path(__file__).resolve().parent
CORE=HERE.parents[1]/'rtl/decode_os_core.sv'

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    output=args.output.resolve()
    if output.exists(): raise SystemExit('Choose a new output directory')
    output.mkdir(parents=True)
    os.environ['PATH']=str(Path(sys.executable).parent)+os.pathsep+os.environ['PATH']
    sources=[HERE/'decode_compute_timing_harness.sv',HERE/'bufg_sim.sv',
             HERE/'scan_core_fixture.sv',CORE]
    verified_files=sources+[HERE/'test_timing_harness.py',HERE/'run_harness_tests.py',HERE/'harness_constraints.tcl']
    hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in verified_files}
    cases=[]
    for p,c,stub in [(1,3,True),(2,5,True),(1,3,False),(2,5,False)]:
        build=output/f'p{p}_c{c}_stub{int(stub)}'
        runner=get_runner('verilator')
        runner.build(sources=[sources[0],sources[1],sources[2] if stub else CORE],
            hdl_toplevel='decode_compute_timing_harness',build_dir=build,
            parameters={'PARTITIONS':p,'COLS':c},always=True,
            build_args=['-Wall','-Wno-DECLFILENAME','-Wno-UNUSEDSIGNAL','-Wno-UNUSEDPARAM'])
        runner.test(hdl_toplevel='decode_compute_timing_harness',
            test_module='test_timing_harness',test_dir=HERE,build_dir=build,
            results_xml=str(build/'results.xml'),extra_env={
                'HARNESS_PARTITIONS':str(p),'HARNESS_COLS':str(c),'HARNESS_STUB':str(int(stub))})
        tree=ElementTree.parse(build/'results.xml').getroot()
        if not tree.findall('.//testcase') or tree.findall('.//failure') or tree.findall('.//error'):
            raise SystemExit(f'Failed harness case P={p}, C={c}, fixture={stub}')
        cases.append(dict(partitions=p,cols=c,mapping_fixture=stub,status='passed',
                          tests=len(tree.findall('.//testcase'))))
    if hashes != {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in verified_files}:
        raise SystemExit('Source changed during verification')
    summary={'status':'passed','scope':'Functional serial harness tests only; no physical timing claim',
             'cases':cases,'source_sha256':hashes,
             'verilator':subprocess.check_output(['verilator','--version'],text=True).strip()}
    (output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary,indent=2))

if __name__=='__main__':main()
