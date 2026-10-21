"""Run Verilator boundary checks plus a standalone Icarus four-state bench."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from xml.etree import ElementTree

import cocotb
from cocotb_tools.runner import get_runner


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--rtl-root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--build-root', type=Path)
    args = parser.parse_args()
    root = args.rtl_root.resolve()
    test_dir = Path(__file__).resolve().parent
    build_root = args.build_root or root / 'build' / 'os_boundaries'
    os.environ['PATH'] = str(Path(sys.executable).parent) + os.pathsep + os.environ['PATH']
    files = {'rtl/decode_os_core.sv': root / 'rtl/decode_os_core.sv',
             'tests/test_os_core.py': root / 'tests/test_os_core.py',
             **{f'tests/{name}': test_dir / name for name in (
                 'test_os_boundaries.py', 'run_os_boundaries.py', 'os_four_state_tb.sv')}}
    def hashes():
        return {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in files.items()}
    before = hashes()
    reports = []
    for sim in ('verilator',):
        build = build_root / sim
        runner = get_runner(sim)
        runner.build(sources=[root / 'rtl' / 'decode_os_core.sv'],
                     hdl_toplevel='decode_os_core', parameters={'PARTITIONS': 4, 'COLS': 8},
                     build_dir=build, build_args=['-Wall'], always=True, clean=True)
        runner.test(hdl_toplevel='decode_os_core', test_module='test_os_boundaries',
                    test_dir=test_dir, build_dir=build, results_xml=str(build / 'results.xml'),
                    extra_env={'DECODE_PARTITIONS': '4', 'DECODE_COLS': '8', 'DECODE_RTL_ROOT': str(root)})
        xml = ElementTree.parse(build / 'results.xml').getroot()
        count = len(xml.findall('.//testcase'))
        assert count == 2 and not xml.findall('.//failure') and not xml.findall('.//error'), sim
        reports.append({'simulator': sim, 'tests': count, 'status': 'passed'})
    # A native SV bench avoids requiring architecture-matched cocotb VPI on
    # hosts where Icarus runs under Rosetta and Python runs natively.
    binary = build_root / 'os_four_state'
    subprocess.run(['iverilog', '-g2012', '-Wall', '-s', 'os_four_state_tb',
                    '-o', str(binary), str(root / 'rtl/decode_os_core.sv'),
                    str(test_dir / 'os_four_state_tb.sv')], check=True)
    result = subprocess.run(['vvp', str(binary)], check=True, text=True, capture_output=True)
    assert 'PASS four-state' in result.stdout
    print(result.stdout, end='')
    reports.append({'simulator': 'icarus', 'tests': 3, 'status': 'passed',
                    'checks': 'X on unused lanes/seeds, result arithmetic, stalls and reset'})
    assert before == hashes(), 'sources changed during verification'
    def version(command):
        output = subprocess.run(command, check=True, text=True, capture_output=True)
        return output.stdout.splitlines()[0]
    result = {'status': 'passed', 'reports': reports,
              'tools': {'verilator': version(['verilator', '--version']),
                        'iverilog': version(['iverilog', '-V']), 'cocotb': cocotb.__version__},
              'source_sha256': before}
    (build_root / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
    print('PASS directed maximum-K, signed wrap and command protocol checks')


if __name__ == '__main__':
    main()
