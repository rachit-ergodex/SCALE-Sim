"""Run decode RTL verification and bind retained evidence to source hashes."""
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import subprocess
import sys
from xml.etree import ElementTree

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]

def source_hashes():
    sources=[p for folder in ('rtl','tests','switchboard','generated') for p in (HERE/folder).glob('*')
             if p.is_file() and p.suffix in ('.sv','.py','.cpp','.json')]
    sources += [HERE/'generate.py',HERE/'requirements.txt',HERE/'verify.py',
                ROOT/'scalesim/compute/systolic_compute_os.py',ROOT/'scalesim/scale_config.py']
    return {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(sources)}

def collect(before):
    assert before==source_hashes(),'Sources changed during verification'
    cases=json.loads((HERE/'build/cocotb_summary.json').read_text())
    assert len(cases)==6 and all(c['status']=='passed' for c in cases)
    xml=[]
    for p in sorted((HERE/'build').glob('decode_*/results.xml')):
        root=ElementTree.parse(p).getroot()
        assert not root.findall('.//failure') and not root.findall('.//error')
        xml += [{'name':test.get('name'),'module':test.get('classname'),'simulation_ns':test.get('sim_time_ns')}
                for test in root.findall('.//testcase')]
    assert len(xml)==6
    switchboard=json.loads((HERE/'build/switchboard/summary.json').read_text())
    synthesis=json.loads((HERE/'build/synthesis/summary.json').read_text())
    assert switchboard['status']=='passed' and switchboard['cases']==24
    assert len(synthesis)==6 and all(s['status']=='passed' for s in synthesis)
    hbm=json.loads((HERE/'hbm_read_verification.json').read_text())
    assert hbm['status']=='passed'
    for name,digest in hbm['source_sha256'].items():
        assert hashlib.sha256((HERE/name).read_bytes()).hexdigest()==digest
    bridge=json.loads((HERE/'hbm_bridge_verification.json').read_text())
    assert bridge['status']=='passed'
    for name,digest in bridge['source_sha256'].items():
        assert hashlib.sha256((HERE/name).read_bytes()).hexdigest()==digest
    directed=json.loads((HERE/'hbm_directed_verification.json').read_text())
    boundaries=json.loads((HERE/'build/os_boundaries/summary.json').read_text())
    for extra in (directed,boundaries):
        assert extra['status']=='passed'
        for name,digest in extra['source_sha256'].items():
            assert hashlib.sha256((HERE/name).read_bytes()).hexdigest()==digest
    report={'status':'passed','scope':'Compute core and standalone memory/control blocks; not full-transformer RTL or physical FPGA validation',
        'sources_sha256':before,'tools':{p:version(p) for p in ('cocotb','switchboard-hw','numpy','tqdm')},
        'verilator':subprocess.check_output(['verilator','--version'],text=True).strip(),
        'yosys':subprocess.check_output(['yosys','-V'],text=True).strip(),
        'cocotb_configurations':cases,'cocotb_tests':xml,'switchboard':switchboard,'generic_synthesis':synthesis,'hbm_read_frontends':hbm,'hbm_read_clock_crossings':bridge,'hbm_directed':directed,'compute_boundaries':boundaries,
        'generated_target_lint':['decode_asic_compute','decode_f2_compute']}
    (HERE/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print('PASS decode RTL verification; evidence saved to verification.json')

def main():
    before=source_hashes()
    subprocess.run([sys.executable,str(HERE/'generate.py'),'--check'],check=True)
    for target in ('asic','f2'):
        top=f'decode_{target}_compute'
        subprocess.run(['verilator','--lint-only','-Wall','--top-module',top,str(HERE/'rtl/decode_os_core.sv'),str(HERE/'generated'/f'{top}.sv')],check=True)
    for script,args in [('run_cocotb.py',['--full']),('run_switchboard.py',[]),('run_synthesis.py',[]),('run_hbm_read32.py',[]),('run_hbm_bridge.py',[]),('run_hbm_directed.py',[]),('run_os_boundaries.py',[])]:
        subprocess.run([sys.executable,str(HERE/'tests'/script),*args],check=True)
    collect(before)

if __name__=='__main__':main()
