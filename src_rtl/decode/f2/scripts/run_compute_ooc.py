#!/usr/bin/env python3
"""Snapshot and run the full 64 x 64 compute component at a 200 MHz OOC target."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[4]
BASE = Path("src_rtl/decode")
RTL = (BASE / "rtl/decode_os_core.sv", BASE / "generated/decode_f2_compute.sv")
INPUTS = (*RTL, BASE / "generated/decode_f2_compute.json", BASE / "verification.json",
          BASE / "f2/constraints/compute_200mhz.xdc",
          BASE / "f2/scripts/compute_ooc.tcl", BASE / "f2/scripts/run_compute_ooc.py",
          BASE / "f2/scripts/audit_compute_ooc.py")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path, help="New experiment directory")
    parser.add_argument("--vivado", default="vivado", help="Vivado executable (2025.2 reference)")
    parser.add_argument("--stage", choices=("synth", "route"), default="route")
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--dry-run", action="store_true", help="Check sources and print plan; no build")
    args = parser.parse_args()
    if not 1 <= args.threads <= 32:
        parser.error("--threads must be between 1 and 32")
    output = args.output.resolve()
    if output.exists():
        parser.error("--output must not already exist; preserve previous experiments")
    verification = json.loads((ROOT / BASE / "verification.json").read_text())
    if verification.get("status") != "passed":
        parser.error("The functional verification manifest does not pass")
    for path in RTL:
        if sha(ROOT / path) != verification["sources_sha256"].get(str(path)):
            parser.error(f"Functional verification is stale for {path}; rerun compute verification")
    hashes = {str(path): sha(ROOT / path) for path in INPUTS}
    source = output / "source"
    vivado = shutil.which(args.vivado)
    executable = vivado or args.vivado
    command = [executable, "-mode", "batch", "-nojournal", "-log", str(output / "vivado.log"),
               "-source", str(source / BASE / "f2/scripts/compute_ooc.tcl"), "-tclargs",
               str(source), str(output), args.stage, str(args.threads)]
    manifest = {
        "status": "planned", "created_utc": datetime.now(timezone.utc).isoformat(),
        "part": "xcvu47p-fsvh2892-2-e", "compute_mhz": 200, "macs": 4096,
        "stage": args.stage, "source_hashes": hashes, "command": command,
        "scope": "Compute-only OOC; full-device placement, no AWS shell, HBM or SRAM adapter",
        "boundary_budget_ns": {"input_max": 1, "output_max": 1, "input_min": 0,
                               "output_min": 0, "setup_uncertainty": 0.25, "hold_uncertainty": 0.1},
        "historical_simulator_profile_mhz": 250,
        "f2_shell_timing_closed": False,
    }
    print(shlex.join(command), flush=True)
    if args.dry_run:
        print(json.dumps(manifest, indent=2))
        return 0
    if not vivado:
        parser.error(f"Vivado executable not found: {args.vivado}")
    output.mkdir(parents=True)
    for path in INPUTS:
        destination = source / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / path, destination)
        if sha(destination) != hashes[str(path)]:
            raise RuntimeError(f"Source changed while taking snapshot: {path}")
    version = subprocess.run([executable, "-version"], text=True,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (output / "vivado_version.txt").write_text(version.stdout)
    manifest["status"] = "running"
    manifest_path = output / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    try:
        with (output / "console.log").open("w") as log:
            result = subprocess.run(command, cwd=output, stdout=log, stderr=subprocess.STDOUT)
        manifest["vivado_returncode"] = result.returncode
        if result.returncode:
            manifest["status"] = "vivado_failed"
            return result.returncode
        audit = subprocess.run([sys.executable, str(source / BASE / "f2/scripts/audit_compute_ooc.py"),
                                str(output)], cwd=output)
        manifest["status"] = "passed" if audit.returncode == 0 else "audit_failed"
        return audit.returncode
    except BaseException:
        manifest["status"] = "interrupted_or_failed"
        raise
    finally:
        manifest["finished_utc"] = datetime.now(timezone.utc).isoformat()
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        print(f"Run artifacts: {output}", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
