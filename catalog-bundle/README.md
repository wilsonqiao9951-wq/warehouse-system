# Public catalog bundle

Only public source indexes, normalized catalog views and JSON review decisions belong here. No organization operational database, customer work orders, uploads, credentials or raw HTML snapshots are included.

Restore from the repository root: `python -m scripts.install_catalog_bundle`.
Rebuild after verified data edits: `python -m scripts.build_catalog_bundle`.

Chunks are independent Base64 encodings of consecutive gzip archive segments. The installer validates each chunk, the reconstructed archive and every extracted file against manifest.json. This encoding allows the existing GitHub connector to publish the complete dataset as bounded UTF-8 files. Docker and CI restore the bundle before running the backend. Large expanded JSON files are not duplicated in Git.
