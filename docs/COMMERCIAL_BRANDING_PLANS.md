# Commercial branding and plan controls

This guide covers the first Phase 9 commercial control plane: tenant branding,
subscription access state, plan entitlements, and user/warehouse capacity.

## Plan defaults

Plan selection applies the following standard limits. A platform administrator can
store explicit customer overrides after selecting the plan.

| Plan | Active users + pending invitations | Main warehouses | Vehicle inventories | AI requests/month | API requests/month |
|---|---:|---:|---:|---:|---:|
| Starter | 5 | 1 | 1 | 0 | 0 |
| Professional | 50 | 10 | 50 | 2,000 | 10,000 |
| Enterprise | Contract | Contract | Contract | Contract | Contract |

`null` means unlimited or contract-governed. Usage is still counted for an
unlimited organization. `0` means the capability is not included and the
metered endpoint returns `403`. A positive allowance is enforced atomically;
the first request beyond the allowance returns `429`.

Changing a plan resets all five limits to its defaults before explicit values in
the same update are applied.

## Subscription access states

| State | Customer password login | Existing access token | External API key |
|---|---|---|---|
| `trialing` with a future end | Allowed | Allowed | Allowed |
| `trialing` without a future end | Blocked | Blocked | Blocked |
| `active` | Allowed | Allowed | Allowed |
| `past_due` | Blocked | Blocked | Blocked |
| `suspended` | Blocked | Blocked | Blocked |
| `cancelled` | Blocked | Blocked | Blocked |

Setting `is_active=false` also blocks customer access. Platform administrators
bypass their home organization's commercial state so they can restore customer
service from `/platform`.

The public branding endpoint remains available for an active organization even
when its trial or subscription is blocked. This lets the customer-specific login
page explain the server's authenticated access result without exposing plan,
capacity, user, or billing data.

## Tenant branding

Organization administrators manage branding under `/settings`:

- HTTPS logo URL
- Six-digit hexadecimal primary color
- Login headline

The branded customer link is:

```text
/login?organization={organization-slug}
```

The app shell loads authenticated organization branding. The login page can load
the safe public branding projection:

```http
GET /api/auth/organization-branding/{slug}
```

The public response contains only company name, slug, logo URL, primary color,
and login headline. Logo URLs must use HTTPS, cannot contain embedded
credentials, and cannot contain characters that can escape the CSS URL context.
SVG content is displayed only as a browser image background.

Branding updates require an organization administrator and the current
`settings_version`:

```http
PATCH /api/organization/settings/branding
Content-Type: application/json

{
  "expected_version": 3,
  "brand_logo_url": "https://cdn.example.com/company/logo.png",
  "brand_primary_color": "#123456",
  "brand_login_headline": "Welcome to ACME Field Service"
}
```

A stale version returns `409` and does not overwrite a newer change. Successful
updates increment the version and create an organization audit event containing
only changed field names, not the submitted branding content.

## Capacity rules

User capacity includes:

```text
active users + unexpired pending invitations
```

Creating an invitation, accepting an invitation, and directly creating a user
all acquire the organization capacity lock before counting. Reissuing an
invitation for the same email does not consume a second seat. Directly creating
the invited user consumes the existing reserved seat and closes that pending
invitation.

Warehouse capacity counts active records separately:

- `main` uses `max_warehouses`
- `van` uses `max_vehicle_warehouses`

Capacity limits prevent new active records; lowering a limit below current usage
does not delete or deactivate existing customer data. The customer must reduce
usage or receive a larger limit before creating more records.

Organization users can read their current plan and usage:

```http
GET /api/organization/settings
```

The response includes `usage_period_start`, `ai_monthly_used`, and
`api_monthly_used`. Settings and the platform customer list show the same
current-period counters beside each allowance.

## Monthly AI and API metering

OpenPartsFlow stores one tenant-isolated usage row per UTC calendar month. A
new month automatically starts a new row at zero; prior rows remain available
as durable commercial evidence.

| Request | AI units | API units |
|---|---:|---:|
| Work-order part recommendations | 1 | 0 |
| Work-order service intelligence | 1 | 0 |
| Visual part candidate generation | 1 | 0 |
| External inventory read | 0 | 1 |
| External linked work-order status read | 0 | 1 |
| External linked work-order recommendations | 1 | 1 |
| New successful external work-order upsert | 0 | 1 |
| Exact replay of a processed idempotency key | 0 | 0 |

Authentication failures, validation failures, missing resources, rejected
work-order mutations, and rolled-back server errors do not consume capacity.
For inbound work orders, the usage increment is committed in the same final
transaction as the work order and processed synchronization log. Exact
idempotent replays return the stored response without another charge.

Allowance decisions serialize on the organization row with PostgreSQL row
locking or a SQLite immediate write transaction. Therefore two concurrent
requests competing for the final unit cannot both succeed. Counters and their
last-used timestamps never contain request payloads, API keys, image data, or
AI response content.

Only platform administrators can change plans, subscription state, trial dates,
or capacity:

```http
PATCH /api/platform/organizations/{organization_id}
Content-Type: application/json

{
  "expected_version": 5,
  "plan_code": "professional",
  "subscription_status": "active",
  "trial_ends_at": null,
  "max_users": 60
}
```

Platform updates use the same optimistic `settings_version`. Trial dates received
with a timezone are normalized to naive UTC before database comparison and
storage.

## Audit and isolation

- Branding mutation is restricted to the authenticated organization
  administrator.
- Commercial mutation is restricted to a platform administrator.
- Every settings read and capacity count is organization-scoped.
- Public branding never returns plan, subscription, trial, quota, user, or usage
  data.
- Organization creation and commercial changes create platform audit events.
- Branding changes create organization audit events.
- Audit metadata excludes passwords, API keys, invitation tokens, and logo or
  headline content.
- Subscription checks run for password login, every authenticated token request,
  invitation use, and external API-key requests.

## Deployment

Apply migration `20260806_0035` before starting the updated application:

```bash
alembic upgrade head
```

Revision `0032` assigns existing organizations the Professional defaults and
active subscription state. Revision `0033` creates the monthly usage ledger.
Revision `0034` adds verified customer domains. Revision `0035` adds provider
bindings, ordered lifecycle events, and durable subscription notices.
Downgrades are refused when the corresponding customer evidence exists.

## Next Phase 9 batches

- Provider-specific checkout, invoice, tax, refund, and restricted customer
  billing-recovery portal integration
- Customer data export and backup/restore evidence
- MFA and account recovery for platform and organization administrators

Verified hostname ownership, automatic custom-host login branding, and the
provider-independent customer sender identity foundation are documented in
[`VERIFIED_DOMAINS.md`](VERIFIED_DOMAINS.md).

Provider-neutral signed lifecycle events, ordering rules, and trial/renewal
notices are documented in [`BILLING_LIFECYCLE.md`](BILLING_LIFECYCLE.md).

Tenant/platform usage reports and audited CSV rules are documented in
[`COMMERCIAL_REPORTING.md`](COMMERCIAL_REPORTING.md).
