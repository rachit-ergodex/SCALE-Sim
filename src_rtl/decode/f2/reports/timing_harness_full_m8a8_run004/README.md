# M8a full-array relaunch, run004

Started October 21, 2026 at 21:46:37 IST on `i-053000112615d30d5` (`m8a.8xlarge`).
The native observation records synthesis running; resource fit and routed timing
are pending. The durable runner starts 100 MHz P&R only after the existing
source/checkpoint/DSP/resource checks pass. This is an analysis-only compute
harness, not an F2 shell/HBM image.

- `prerequisite_audit.json` and `audit_prerequisites.py`: all 38 canonical source
  hashes, 12 flow inputs, two 38-file small physical collections and 48 mapped
  simulation artifacts checked. Existing methodology-report limitation retained.
- `host_preflight.json`, `vendor_preflight.json`: Python 3.12.3, Vivado 2025.2
  build 6299465, RAM/disk and actual DSP48E2/glbl model identity.
- `source_upload.json`, `source_extract.json`, `runner_upload.json`,
  `launch_provenance.json`: exact uploaded source/runner identities.
- `runner_local_tests.log`, `runner_review_tests.log`, `runner_review.json`,
  `runner_linux_tests.json`: 60 local/independent flow tests and 15 Linux runner
  tests passed. Earlier failed development test attempts are not build results.
- `instance_launch.json`, `launch_pipeline.sh`, `launch_result.json`: instance
  provisioning and actual systemd launch; encrypted 300 GiB root disk is retained
  if the instance is terminated. Logs/checkpoints live on this disk.
- `observation_ssm.json`, `observation.json`: the saved native observation.

[Run record](../../timing_harness_full_m8a8_run004.json) binds the artifact hashes
and distinguishes an active synthesis from a passing resource or timing result.
