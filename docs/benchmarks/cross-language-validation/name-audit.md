# Old-name search classification

The repository-wide native ripgrep scan found the old name only in preserved evidence, frozen protocol/provenance metadata and migration code. Windows could not read generated Linux symlinks, so the scan was repeated with WSL grep (ripgrep was unavailable there); that scan completed successfully. Both match lists are retained.

Intentional references:
- `docs/benchmarks/validation-amd64/`: immutable prior validation records and archived documentation.
- `docs/benchmarks/cross-language-validation/`: initial snapshots, rename mappings, preserved originals, and this audit.
- New canonical C `config.json` files: the historical `benchmark_version` identifier remains protocol provenance; active `benchmark` is `linux-utilities` and `protocol_version` is 1.
- Canonical and archived frozen `MANIFEST.json` / held-out metadata: original identity and hashes are preserved; regenerated provenance uses the new name with its recomputed fingerprint.
- `scripts/prepare_linux_names.py`: explicit old-to-new migration mappings.
- `scripts/document_cross_language.py`: a reference to the preserved pre-rename methodology used to retain its architecture audit.

No active Docker, manifest, prompt, judge, planner, bundler or reproduction-command path uses the old benchmark directory. Historical artifacts were not renamed to eliminate intentional provenance strings. No functional corpus assertion was changed by the naming cleanup.

Compressed corpora were audited through parsed metadata, content hashes and exact case comparisons; their preserved protocol/provenance identifiers were not removed by text replacement.
