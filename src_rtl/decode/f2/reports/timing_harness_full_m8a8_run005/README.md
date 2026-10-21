# Retry005 launch and running observation

This is an immutable point-in-time snapshot of full 64×64 / 4,096-MAC, 100 MHz compute-harness synthesis on `m8a.8xlarge` instance `i-053000112615d30d5`. The fresh progress observation was captured at **2026-10-21T18:35:28.845463+00:00** (00:05:28 IST on October 22, 2026). The pipeline and synthesis manifests were running. This snapshot does not establish successful synthesis, a passed resource gate, P&R completion, timing closure, inference throughput, or an F2 image.

The six files in `collection_manifest.json`'s `native_files` map preserve exact remote bytes: pipeline provenance/status, synthesis manifest/tool version, the completed synthesis preflight log, and the parent dry-run output. Each has its own read interval, size, source path, and SHA256. The live run may have advanced since collection; these files are not current-state monitors.

`progress.txt` preserves output from the included `status005.sh`; `progress.json` is its parsed representation. The actual Vivado process, PID 3294, had a **256 MiB soft stack limit** with unlimited hard stack and unlimited soft/hard core-file limits. `launch_retry005.sh` and `launch_ssm.json` document those process-limit changes. They do not establish the cause of run004's crash or show that the retry resolves it.

The two frozen 12-file source snapshots and runner hash match failed run004 exactly. No RTL, constraint, or verification changes distinguish this retry. `collection_manifest.json` records those checks and the absence of synthesis checkpoint/readiness/resource/mapping/utilization and route artifacts at capture time. The pipeline will attempt routing only after all existing readiness and resource gates pass.

`initial_observation_ssm.json` preserves the earlier launch observation; `snapshot_ssm.json` records the new collection command result. `transfer_manifest.json` binds the archive and every content file by SHA256 and size. Full moving synthesis logs and raw crash reports are intentionally outside this launch snapshot.
