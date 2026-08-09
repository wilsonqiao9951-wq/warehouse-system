# AppSheet and Google Sheets parallel-run contracts

OpenPartsFlow stores a governed field and automation contract for each external
integration. The contract turns an AppSheet discovery export or Google Sheets
workbook review into versioned evidence that can be checked before a parallel
run. It documents external-only columns without granting those columns any API
access.

## API

- `GET /api/integrations/{integration_id}/parity-contract` returns the saved
  contract, or a provider-aware unsaved template when no contract exists.
- `PUT /api/integrations/{integration_id}/parity-contract` validates and saves
  the contract with `expected_version` optimistic concurrency.

Managers and administrators may read. Only administrators, or a user explicitly
granted `integrations.manage`, may save. Every lookup remains tenant-scoped.

## Contract structure

Each contract records:

- the external metadata revision or discovery date;
- required OpenPartsFlow capabilities;
- external tables, stable key columns, data types, direction, required flags,
  notes, and optional canonical field mappings;
- AppSheet Bots or sheet automations with trigger, direction, capability, action,
  and enabled state;
- covered capabilities, readiness score, blocking gaps, warnings, version,
  actor, server validation time, and a SHA-256 source fingerprint.

An external column with `canonical_field: null` remains in the dictionary for
discovery and reconciliation, but OpenPartsFlow neither reads nor writes it.

## Readiness capabilities

The validator can govern seven capabilities:

1. idempotent work-order intake;
2. linked work-order status reads;
3. inventory reads;
4. explainable recommendation reads;
5. signed status callbacks;
6. signed completion callbacks;
7. signed part-usage callbacks.

Readiness requires the necessary key and data columns, compatible directions,
matching live inbound field mapping, enabled automation contracts, and the
corresponding live Webhook subscriptions. Saving a contract does not configure
or invoke an external system.

## Security boundary

The canonical catalog is an allowlist. Unknown fields are rejected, including
engineer assignment, device identity, signature, completion approval, pricing,
and inventory mutation fields. Inventory and recommendation contract fields are
read-only. Existing work-order ownership, device binding, completion evidence,
inventory custody, API-key, HMAC, idempotency, and tenant checks remain
authoritative.

Contract payloads are limited to 1 MiB, 20 tables, 200 columns per table, and 50
automations. Duplicate table, column, canonical-field, capability, or automation
names are rejected. The database table has forced PostgreSQL row-level security.

## Parallel-run workflow

1. Export the AppSheet table/column dictionary and Bot definitions, or review the
   Google Sheets tabs, headers, formulas, and Apps Script automations.
2. Open `/integrations`, select the integration, and load the generated contract
   template.
3. Record the source revision and add every external column. Leave unsupported
   fields unmapped instead of inventing a canonical field.
4. Describe every Bot or automation and save. Resolve all blocking gaps.
5. Download the fingerprinted JSON contract for customer sign-off.
6. Run both systems for one or two operating cycles and reconcile work orders,
   status, used parts, and inventory before cutover.

Real customer metadata, formulas, security filters, attachment rules, volumes,
and business acceptance remain external inputs. The workbench makes those
inputs explicit and reviewable; it does not claim customer parity without them.
