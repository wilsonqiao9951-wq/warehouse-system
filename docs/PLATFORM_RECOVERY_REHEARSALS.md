# Platform recovery points and scale rehearsals

OpenPartsFlow now has an executable platform-level disaster-recovery path. It
is separate from customer portable exports and controlled tenant restores.
Those customer workflows recover an allowlisted subset of one organization's
business data; they cannot rebuild a lost PostgreSQL service and its evidence
volumes.

## Complete recovery boundary

One platform recovery point contains all four durable data sets from the same
closed-write maintenance window:

- PostgreSQL custom-format logical archive;
- public work-order evidence;
- protected knowledge and recognition evidence;
- controlled-restore rollback evidence.

The generated `opf-platform-recovery-v1` manifest records a random recovery
point ID, UTC creation time, source revision, Alembic revision, exact per-table
row counts, database archive SHA-256, and every evidence file's relative path,
byte count, and SHA-256. Each evidence volume is also hash-protected as a gzip
tar archive. The canonical manifest hash is written separately.

The manifest contains schema and aggregate recovery evidence only. It does not
contain database credentials, host names, customer field values, source file
system paths, media content, or external payloads. Store the recovery point and
its manifest hash in encrypted, access-controlled, off-host storage; the hash
file is an integrity check, not a digital signature or a substitute for WORM
retention.

## Create a recovery point

Recovery-point and restored-volume publication uses same-filesystem atomic
replacement. Because Windows antivirus/indexing can briefly hold a newly
written directory, `PermissionError` is retried six times with a short bounded
backoff; persistent permission failures still abort and clean the staging path.

Create `PLATFORM_RECOVERY_ROOT` and `PLATFORM_RECOVERY_REPORT_ROOT` on the
encrypted backup target and make them writable by UID/GID `10001`. Close user
writes at the gateway before starting. Then run:

```bash
docker compose --env-file .env.production \
  -f docker-compose.production.yml \
  --profile recovery run --rm recovery-backup
```

The purpose-built recovery image is pinned to PostgreSQL 16 client utilities,
runs as non-root with no Linux capabilities, mounts the three live evidence
volumes read-only, and writes only under `PLATFORM_RECOVERY_ROOT`. It supplies
the migration-owner database URL through the environment so the password never
appears in process arguments or reports.

The database credential must have `BYPASSRLS` (the reference Compose owner is a
PostgreSQL superuser). The restricted application role is deliberately refused:
a tenant-scoped dump cannot be represented as a complete platform recovery
point. The tool compares exact schema/table counts before and after `pg_dump`
and rejects visible write drift, but the gateway write freeze remains mandatory
to keep database rows and evidence volumes at one business recovery point.

The command refuses symbolic links, non-regular evidence entries, nested source
and output roots, unsupported database URL options, multiple Alembic heads, and
an existing recovery-point ID. It writes into a private temporary directory and
publishes the completed directory only after all archives and hashes exist.
Restore normal traffic only after copying the completed point off-host and
recording its ID and manifest SHA-256.

## Run an isolated restore rehearsal

Never rehearse against the source database. Provision a new empty PostgreSQL
database in an isolated environment with no customer ingress, set a protected
`TARGET_DATABASE_URL`, and select the recovery point and report filename:

```bash
export TARGET_DATABASE_URL='postgresql+psycopg://owner:REDACTED@db:5432/opf_rehearsal_20260808'
export RECOVERY_POINT_PATH='/recovery/opf-recovery-20260808T220000Z-example'
export RECOVERY_REPORT_PATH='/reports/rehearsal-20260808.json'

docker compose --env-file .env.production \
  -f docker-compose.production.yml \
  --profile recovery run --rm recovery-rehearsal

docker compose --env-file .env.production \
  -f docker-compose.production.yml \
  --profile recovery run --rm recovery-rehearsal \
  verify-report --report "$RECOVERY_REPORT_PATH" \
  --max-rpo-seconds 86400 --max-rto-seconds 3600
```

The restore command refuses the source database, a non-empty target database,
existing evidence targets, missing/unexpected recovery files, manifest drift,
archive drift, unsafe tar members, schema drift, row-count drift, and evidence
file drift. It validates every archive before changing the isolated target,
extracts to staging directories, restores PostgreSQL with `--exit-on-error`,
rechecks the exact Alembic revision and table counts, and promotes evidence only
after verification.
PostgreSQL restore runs in one transaction and only accepts a recovery point
created by a trusted OpenPartsFlow deployment. Do not treat this mechanism as
an upload parser for third-party dumps: restoring a database archive executes
schema statements carried by that trusted archive.

The `opf-platform-recovery-rehearsal-v1` report retains only recovery-point and
manifest identity, schema revision, aggregate row/file/byte counts, measured
RPO (recovery-point age when the rehearsal starts), measured RTO, server times,
and isolation confirmation. It contains no credentials, target identity,
business values, or file paths. Review it, drop the rehearsal database, and
destroy the isolated restored volumes after evidence retention is complete.

## CI recovery gate

`python -m scripts.verify_disaster_recovery --confirm-isolated-ci` runs only
against loopback PostgreSQL. It creates a unique empty database, creates a real
custom-format dump plus three evidence archives, restores and verifies them,
checks a 300-second RPO and 120-second RTO regression budget, and drops the
database even after a failure. GitHub Actions runs this against PostgreSQL 16.

These CI budgets prove that the recovery mechanism remains executable for the
test fixture. They do not establish a customer's production RPO/RTO; every
deployment must measure its own data size, backup target, network, storage, and
operating procedure.

## Repeatable scale gate

`python -m scripts.verify_scale_performance --confirm-isolated-ci` also requires
loopback PostgreSQL. In one rolled-back transaction it creates two tenants,
40,000 work orders, 40,000 part-use rows, and 80,000 inventory transactions by
default. It then runs the production-shaped recent-work-order, scheduled-work,
inventory-ledger, engineer part-use, and parts-cost queries repeatedly.

The gate records p50/p95 latency, plan node types, and index names. It first
proves that every tenant-led `0067` index exists in the PostgreSQL catalog, then
fails if a protected large table regresses to a sequential scan, a query does
not use any index, or p95 exceeds the deliberately broad 750 ms CI budget.
Exact index selection remains PostgreSQL's cost-based decision. The synthetic
transaction is always rolled back and uses explicit temporary identifiers so it
does not advance production sequences. The report contains only scale, plans,
and timings and explicitly is not a capacity certification or contractual SLA.

Migration `20260808_0067` adds the tenant-led pagination and range indexes used
by this gate. Controlled tenant restore compatibility is extended through
`0067` because migrations `0065` through `0067` do not change the allowlisted
portable record format.
