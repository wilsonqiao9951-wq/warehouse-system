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

`null` means unlimited or contract-governed. `0` means the capability is not
included. AI and API allowances are stored entitlements in this batch; request
metering and hard monthly enforcement are a later Phase 9 batch.

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

Apply migration `20260730_0032` before starting the updated application:

```bash
alembic upgrade head
```

The migration assigns existing organizations the Professional defaults and active
subscription state. Downgrade is allowed only while every organization still has
those untouched defaults; this prevents silent loss of commercial or branding
configuration.

## Next Phase 9 batches

- Durable monthly AI/API usage counters with idempotent charging and period reset
- Plan-feature enforcement for AI and external API calls
- Verified custom domains and customer-specific email identity
- Trial/renewal notifications and billing-provider lifecycle integration
- Customer data export, backup/restore evidence, and commercial usage reports
- MFA and account recovery for platform and organization administrators
