# Full-size synthesis crash: run004

This directory preserves the failed 64×64 / 4,096-MAC, 100 MHz synthesis attempt on `m8a.8xlarge` instance `i-053000112615d30d5`, using Vivado 2025.2 build 6299465. It is failure evidence only: no completed synthesis checkpoint, final utilization/resource gate, P&R, timing closure, inference throughput, or F2 image is established.

`status.json` and `synth/manifest.json` are the exact native final records. The Vivado wrapper and synthesis driver returned **139**; the pipeline supervisor returned **1**, as preserved in `pipeline-launcher-004.log`. The selected Apport summary identifies signal 11, `SIGSEGV`. The root cause is not established by these records.

`console.log` and `vivado.log` under `synth/` retain their native bytes, including the final DSP inference report. That report is preliminary and is not a completed resource gate. Pipeline logs, source provenance, tool version, and both final status records are preserved with their original filenames.

`collection_manifest.json` binds all nine native files by SHA256 and size, verifies both frozen source snapshots and the runner, inventories retained intermediate files, and records the exact absence of `post_synth.dcp`, `synth_ready.txt`, `resource_gate.json`, final DSP mapping/utilization, all DCPs, and the route directory/logs at collection time. Large intermediate files remain on the persistent build volume with hashes recorded.

`apport_selected_summary_ssm.json`, `crash_diagnostics_ssm.json`, and `crash_details_ssm.json` preserve the already selected diagnostic responses. The raw Apport report, which includes process environment data, was not downloaded. Its original SHA256 is retained; the file was moved to `crash-004-original/` on the build volume before the separate retry. No raw process environment contents are included here.

`transfer_manifest.json` records the bounded SSM transfer, archive hash, supplemental evidence hashes, and this README hash. The archive was verified before extraction, every native file hash was rechecked, and native logs were not reformatted. Retry run005 is separate and does not modify this failed run.
