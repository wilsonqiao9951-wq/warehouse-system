# Billing lifecycle and subscription notices

This Phase 9 foundation keeps OpenPartsFlow's commercial access state aligned
with an external billing system without storing card data or trusting
unauthenticated status changes. It is provider-neutral: `manual` mode is
operated in the platform control plane, while `generic` mode accepts a small,
signed lifecycle event contract that a future Stripe, ERP, or reseller adapter
can produce.

This batch does not provide checkout, payment collection, refunds, tax,
invoices, or a customer payment-method portal. It also does not claim a native
Stripe integration. Those capabilities require a separately reviewed provider
adapter.

## Billing account binding

A platform administrator opens `/platform` and binds at most one billing
account to an organization. Saving or changing a binding requires the platform
administrator's current password.

- `manual`: no external references are accepted. Platform commercial controls
  remain authoritative.
- `generic`: both an external customer reference and an external subscription
  reference are required. Each reference is globally unique inside the
  provider namespace.

The binding can also record the current UTC billing period, whether cancellation
is scheduled at period end, and an optional payment grace end. Changes use an
optimistic `version`; stale writes return `409`. Changing either external
reference resets the ordering cursor so the new subscription can establish its
own event timeline.

## Signed lifecycle webhook

The generic receiver is:

```http
POST /api/billing/webhooks/generic
```

Configure a random secret of at least 32 characters in
`BILLING_WEBHOOK_SECRET`. The adapter sends:

```text
X-OpenPartsFlow-Timestamp: <current Unix seconds>
X-OpenPartsFlow-Signature: sha256=<hex HMAC>
```

The signed bytes are:

```text
<timestamp>.<exact request body bytes>
```

The server calculates HMAC-SHA256, compares the fixed-length signature with
`hmac.compare_digest`, and rejects timestamps outside
`BILLING_WEBHOOK_TOLERANCE_SECONDS` (default 300). Python documents
`compare_digest` as the timing-analysis-resistant comparison intended for this
use: [Python `hmac` documentation](https://docs.python.org/3/library/hmac.html).
Payloads over `BILLING_WEBHOOK_MAX_BYTES` (default 64 KiB), missing signatures,
unsafe server configuration, extra JSON fields, and invalid timelines are
rejected before any commercial state changes.

Example event:

```json
{
  "event_id": "evt_2026_08_06_001",
  "event_type": "subscription.renewed",
  "occurred_at": "2026-08-06T16:00:00Z",
  "external_customer_id": "customer_123",
  "external_subscription_id": "subscription_456",
  "plan_code": "professional",
  "current_period_start": "2026-08-06T16:00:00Z",
  "current_period_end": "2026-09-06T16:00:00Z"
}
```

Supported events:

| Event | Result |
|---|---|
| `trial.started` | Sets `trialing`; requires a future trial end |
| `subscription.activated` | Sets `active`; requires a future billing period |
| `subscription.renewed` | Sets `active`; advances the billing period |
| `payment.failed` | Sets `past_due`; may record a grace end |
| `subscription.cancellation_scheduled` | Keeps access state and marks period-end cancellation |
| `subscription.cancellation_reversed` | Clears scheduled cancellation |
| `subscription.suspended` | Sets `suspended` |
| `subscription.cancelled` | Sets `cancelled` and clears scheduled cancellation |

Only trial, activation, and renewal events may change `plan_code`. A signed
event must match both references on the configured organization billing
account. Unknown or partially matching subscriptions return `404` without
revealing another customer's binding.

## Idempotency and ordering

`provider + event_id` is globally unique. The first accepted event stores only
its SHA-256 body digest and normalized lifecycle evidence; the raw provider
payload is not retained. A byte-identical replay returns the original result
with `duplicate: true`. Reusing the event ID with different bytes returns `409`.

Every billing account records its newest applied `occurred_at`. Older or equal
events are retained as `ignored_stale` for audit but cannot roll the customer
backward. Events too far in the future are rejected so a bad provider clock
cannot poison the ordering cursor. Organization status, plan limits, account
cursor, event evidence, audit evidence, and notices commit atomically.

## Subscription notices

The coordinator creates durable notices for:

- trial ending inside `BILLING_NOTICE_WINDOW_DAYS`;
- expired trial;
- renewal inside the notice window;
- billing period ended without a newer lifecycle event;
- scheduled cancellation;
- past-due payment;
- suspended subscription;
- cancelled subscription.

The coordinator runs once when the application starts and then every
`BILLING_RECONCILIATION_POLL_SECONDS` (default one hour). A platform
administrator can also run `POST /api/platform/billing/reconcile`. Each notice
is unique to its organization, type, and effective milestone. When the
underlying condition recovers, the notice becomes `resolved`; a later distinct
failure creates separate evidence.

An overdue renewal notice does not change access by itself: it flags a missing
provider event for platform review. A provider-specific adapter may later apply
its contractually approved grace and suspension policy.

Organization administrators see lifecycle notices in Settings while normal
subscription access is available and can acknowledge an open notice with its
current optimistic version. Because the existing fail-closed authentication
policy blocks past-due, suspended, cancelled, and expired-trial organizations,
recovery for those states remains a platform/provider operation. A future
restricted billing-recovery session must be designed separately before customer
self-service payment repair is offered.

Notices are currently in-app durable records. Email/SMS delivery is not claimed;
it depends on a separately connected outbound notification provider.

## APIs and authorization

Organization administrator:

```text
GET  /api/organization/billing
POST /api/organization/billing/notices/{id}/acknowledge
```

Platform administrator:

```text
GET  /api/platform/billing/accounts
PUT  /api/platform/billing/accounts/{organization_id}
GET  /api/platform/billing/events
GET  /api/platform/billing/notices
POST /api/platform/billing/reconcile
```

The webhook uses HMAC authentication rather than a user token. Billing account,
event, notice, and audit reads remain tenant-scoped outside the platform control
plane. Passwords, webhook secrets, raw provider payloads, payment methods, and
card details are never stored in lifecycle or audit rows.

## Deployment

1. Apply `alembic upgrade head` to install revision `20260806_0035`.
2. Set a unique production `BILLING_WEBHOOK_SECRET` of at least 32 random
   characters if generic webhooks will be enabled.
3. Keep the endpoint behind HTTPS and never put the secret in a URL.
4. Bind the organization and external references in `/platform` before sending
   events.
5. Send a signed activation event, repeat it to verify idempotency, then verify
   the event and audit rows in the control plane.
6. Monitor reconciliation errors and open critical notices.

Downgrade from `0035` is refused while any billing account, lifecycle event, or
subscription notice exists, preventing silent deletion of commercial evidence.
