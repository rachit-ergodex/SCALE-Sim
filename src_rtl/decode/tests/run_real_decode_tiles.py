"""Run full F2 arithmetic component checks on production decode dimensions."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from xml.etree import ElementTree

import cocotb
import numpy as np
from cocotb_tools.runner import get_runner


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--build-root', type=Path)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    build = (args.build_root or root / 'build' / 'real_decode_tiles').resolve()
    report_path = args.report or root / 'real_decode_tiles_verification.json'
    test_dir = root / 'tests'
    sources = [root / 'rtl/decode_os_core.sv',
               test_dir / 'test_real_decode_tiles.py', Path(__file__).resolve()]
    def hashes():
        return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sources}
    before = hashes()
    os.environ['PATH'] = str(Path(sys.executable).parent) + os.pathsep + os.environ['PATH']
    runner = get_runner('verilator')
    runner.build(sources=[sources[0]], hdl_toplevel='decode_os_core',
                 parameters={'PARTITIONS': 64, 'COLS': 64}, build_dir=build,
                 build_args=['-Wall'], always=True, clean=True)
    metrics = build / 'metrics.json'
    runner.test(hdl_toplevel='decode_os_core', test_module='test_real_decode_tiles',
                test_dir=test_dir, build_dir=build, results_xml=str(build / 'results.xml'),
                extra_env={'DECODE_REAL_TILES_METRICS': str(metrics)})
    xml = ElementTree.parse(build / 'results.xml').getroot()
    tests = xml.findall('.//testcase')
    assert len(tests) == 4 and not xml.findall('.//failure') and not xml.findall('.//error')
    assert hashes() == before, 'sources changed during verification'
    cases = json.loads(metrics.read_text())
    assert len(cases) == 4
    commands = [command for case in cases for command in case['commands']]
    result = {
        'status': 'passed',
        'scope': 'Full 64x64 INT8 compute RTL; production-size synthetic operands, not model weights or a full token pipeline',
        'clock_hz': 200_000_000,
        'parameters': {'PARTITIONS': 64, 'COLS': 64, 'physical_macs': 4096},
        'independent_oracle': 'NumPy INT64 matrix multiplication with explicit signed INT32 modular wrap',
        'checks': ['every requested A/B and active C address', 'all valid masks',
                   'all accepted outputs exactly once', 'INT32 accumulated K partials',
                   'parallel rows, multiple waves and ragged output tiles',
                   'minimum/maximum signed INT8 and INT32 wrap',
                   'random backpressure and 11-cycle output stalls',
                   'poison values on unused operand and partial-sum inputs',
                   'logical/elapsed/stall cycle counters'],
        'tests': len(tests), 'commands': len(commands),
        'checked_command_outputs': sum(command['checked_outputs'] for command in commands),
        'checked_final_outputs': sum(case['checked_final_outputs'] for case in cases),
        'logical_cycles': sum(command['logical_cycles'] for command in commands),
        'stall_cycles': sum(command['stall_cycles'] for command in commands),
        'wall_seconds': sum(float(test.get('time')) for test in tests),
        'cases': cases,
        'tools': {'verilator': subprocess.check_output(['verilator', '--version'], text=True).strip(),
                  'cocotb': cocotb.__version__, 'numpy': np.__version__},
        'source_sha256': before,
        'limitations': ['The 200 MHz simulation period does not establish FPGA timing closure.',
                        'HBM/DMA/CDC and vector/SFU integration are outside these arithmetic component tests.',
                        'These component timings do not establish end-to-end tokens/second.']}
    report_path.write_text(json.dumps(result, indent=2) + '\n')
    print(f'PASS {len(tests)} full-F2 arithmetic tests, {len(commands)} commands, '
          f'{result["checked_command_outputs"]} accepted outputs')
    print(report_path)


if __name__ == '__main__':
    main()
