# Disaster-Recovery Evidence Retention

OpenPartsFlow keeps customer business records and the immutable audit trail
outside this cleanup workflow. The governed retention controls apply only to
portable-export integrity metadata, terminal or abandoned restore rehearsals,
and expired restore rollback packages.

## Policy

Each organization has three independently versioned settings:

| Evidence | Default | Allowed range | Eligibility |
| --- | ---: | ---: | --- |
| Portable-export integrity metadata | 365 days | 30–3650 days | Older than cutoff and not referenced by a retained restore |
| Restore rehearsal records | 90 days | 7–3650 days | `validated`, `rejected`, or `rolled_back` and inactive beyond cutoff |
| Applied restore rollback package | 30 days | 7–3650 days | Stored expiry reached, or a legacy applied record exceeded the current policy |

An `approved` restore is never a cleanup candidate. An `applied` restore keeps
its archive/plan hashes and application evidence after its sensitive rollback
payload is purged. Customer data, inventory ledgers, custody records, billing
events, authentication evidence, and audit logs are never selected.

Policy changes require an organization administrator's current password, a
non-blank reason, and the current organization `settings_version`. A stale
version returns `409` without overwriting a concurrent settings change. The
change is retained in the organization audit log with previous and current day
values; the password is never logged.

The rollback expiry fixed when a restore is applied is not silently rewritten
by a later policy change. The updated rollback period governs future restore
applications; legacy applied rows without a fixed expiry use the current policy
when previewed.

## Preview and cleanup

`GET /api/organization/data-retention` returns the policy, fixed UTC cutoffs,
candidate counts, and rollback database/file bytes. It does not change state.

`POST /api/organization/data-retention/cleanup` requires the current password,
policy version, operational reason, and a bounded batch size (100 by default,
500 maximum). It processes expired rollback packages first, then terminal
rehearsals, then unreferenced export metadata. Repeating the same action after
the candidates are gone is an audited no-op.

Every execution records only safe evidence: operator, role/authentication
method, reason, policy version, cutoffs, affected row IDs, counts, byte totals,
and missing-file anomaly IDs. Rollback field values, archive content, customer
records, file paths, credentials, and tokens are excluded.

## Database and filesystem boundary

Expired database rollback payloads and their hashes are cleared while the
restore row retains application and purge attribution. File evidence is moved
atomically from its active `organization-<id>/restore-<id>` directory to an
organization-specific protected quarantine before the database commit.

- If staging or the database commit fails, moved evidence is returned to its
  active path.
- If the process stops before the commit, the next cleanup recognizes that the
  database rollback payload is still active and restores the directory.
- If the process stops after the commit, the next cleanup sees the committed
  purge and finishes deleting the quarantined directory.
- A post-commit filesystem deletion failure returns a safe pending flag and
  creates a separate audit event; the next cleanup reconciles it.

The quarantine remains below `DATA_RESTORE_ROLLBACK_FILES_ROOT`, outside public
and private media roots. Symbolic links, unexpected directory entries, unsafe
paths, and conflicting active/quarantined evidence fail closed.

## Operator procedure

1. Confirm contractual and regulatory retention requirements for the customer.
2. Generate and securely store a current portable backup outside the
   application host when required by policy.
3. Open Backups, review the fixed-cutoff candidate preview and byte totals.
4. Update the policy separately if needed; refresh after any version conflict.
5. Enter an incident/change reference and current password, then clean one
   bounded batch.
6. Repeat while candidates remain and investigate any pending filesystem or
   missing-evidence audit event.
7. Export and retain the audit record in the customer's approved evidence
   system.

Migration `20260807_0052` adds the policy and restore purge evidence. Its
downgrade is refused after a non-default policy, rollback expiry, or purge
evidence has been recorded.
