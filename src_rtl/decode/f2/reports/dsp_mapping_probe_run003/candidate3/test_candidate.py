from pathlib import Path
import os,sys,json,hashlib
from xml.etree import ElementTree
from cocotb_tools.runner import get_runner
root=Path('/Users/rachittibrewal/.codex/worktrees/decode-over-100-tps/SCALE-Sim')
base=Path(__file__).resolve().parent
core=base/'decode_os_core.sv';test=root/'src_rtl/decode/tests/test_os_core.py'
sys.path.insert(0,str(test.parent));sys.path.insert(0,str(root))
hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in (core,test)}
os.environ['PATH']=str(Path(sys.executable).parent)+os.pathsep+os.environ['PATH']
os.environ['PYTHONDONTWRITEBYTECODE']='1'
runner=get_runner('verilator');build=base/'build'
runner.build(sources=[core],hdl_toplevel='decode_os_core',parameters={'PARTITIONS':4,'COLS':8},build_dir=build,build_args=['-Wall','-DSCALESIM_F2_USE_DSP=1'],always=True,clean=True)
runner.test(hdl_toplevel='decode_os_core',test_module='test_os_core',test_dir=base/'test',build_dir=build,results_xml=str(build/'results.xml'),extra_env={'DECODE_PARTITIONS':'4','DECODE_COLS':'8','PYTHONPATH':str(test.parent)+os.pathsep+str(root),'PYTHONDONTWRITEBYTECODE':'1'})
tree=ElementTree.parse(build/'results.xml').getroot()
assert len(tree.findall('.//testcase'))==2
assert not tree.findall('.//failure') and not tree.findall('.//error')
assert hashes=={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in (core,test)}
summary={'status':'passed','scope':'Temporary per-lane expression RTL checked against existing independent NumPy/native-schedule 4x8 tests, not mapped-netlist or physical closure','tests':2,'source_sha256':hashes,'define':'SCALESIM_F2_USE_DSP=1'}
(base/'verification.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary,indent=2))
