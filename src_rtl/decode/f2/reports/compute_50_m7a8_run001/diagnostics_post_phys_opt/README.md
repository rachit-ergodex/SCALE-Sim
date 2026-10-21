# Pre-route split-path diagnostics

These native reports were generated on October 21, 2026 by reopening the original
`post_phys_opt.dcp` saved **before the failed route attempt**. They separate internal register paths from
input/output boundary paths. They are not terminal routed timing reports and do
not establish timing closure. `collection_manifest.json` binds the reports and
diagnostic Tcl source to the SHA-256 of that saved checkpoint. `transfer.json`
records the verified archive and bounded SSM transfer. All native report and Tcl
bytes are preserved. `summary.tsv` lists the worst sampled path in each category;
its `paths_sampled=1` is not a total failing endpoint count.
