# Commercial usage reporting

OpenPartsFlow now turns the durable monthly AI/API usage ledger into
tenant-scoped customer reports and a cross-customer platform report. The report
does not create a second billing counter: it reads the same UTC period rows used
for quota enforcement.

## Report meaning

Organization administrators can view 1–36 months. Missing ledger months appear
as zero so the timeline remains continuous. Each row contains:

- UTC month start;
- AI request count;
- external API request count;
- last AI/API use timestamps when recorded.

The report also shows current plan, subscription state, limits, active users,
pending invitations, main warehouses, and vehicle inventories. Historical plan
limits are not reconstructed because revisions before this batch did not store
contract snapshots. API and CSV fields therefore label limits and capacity as
current at report generation time; historical request counts remain exact.

Platform administrators can select one UTC month and compare every organization
using the same definitions. An organization with no usage row appears with zero
requests rather than disappearing from the report.

## API

Organization administrator:

```text
GET  /api/organization/commercial-report?months=12
POST /api/organization/commercial-report/export
```

Platform administrator:

```text
GET  /api/platform/commercial-report?period_start=2026-08-01
POST /api/platform/commercial-report/export
```

CSV exports require the current account password in the POST body. Passwords
are neither queued offline nor written to report/audit rows. Each successful
export creates `organization_commercial_report_exported` or
`platform_commercial_report_exported` audit evidence with the range, format,
generation time, and row scope.

## CSV safety and scope

CSV uses a UTF-8 byte-order mark for spreadsheet compatibility and a fixed
server-owned filename. Text beginning with `=`, `+`, `-`, `@`, tab, or carriage
return receives a leading apostrophe to prevent spreadsheet formula execution.

Organization report queries remain under the tenant loader criteria. The
platform report requires the separate platform-administrator permission before
cross-tenant filters are lifted. Reports exclude passwords, password hashes,
API keys, Webhook secrets, invitation tokens, domain challenges, raw billing
payloads, and payment details.

## UI

- `/reports`: organization administrators can review monthly AI/API counts and
  download a password-confirmed CSV.
- `/platform`: platform administrators can select a UTC month, review every
  customer, and export a password-confirmed CSV.

This batch needs no new database revision; it reads revision `0033` usage rows
and existing organization/capacity state. Apply the current Alembic head before
deployment as usual.
