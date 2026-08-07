# Stripe Billing operations

OpenPartsFlow uses Stripe-hosted Checkout and the Stripe customer portal. The
application stores tenant-bound identifiers and operation evidence only; card
numbers, payment methods, redirect URLs, Stripe secrets, raw responses, and raw
webhook bodies are not persisted.

## Configuration

Create recurring Stripe Prices for the plans that can be purchased, then set
the following server-only environment variables:

```text
STRIPE_BILLING_ENABLED=true
STRIPE_SECRET_KEY=sk_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_PRICE_STARTER=price_...
STRIPE_PRICE_PROFESSIONAL=price_...
STRIPE_PRICE_ENTERPRISE=price_...
```

At least one Price is required. Do not expose the secret or webhook secret in
the frontend. Production validation requires the official
`https://api.stripe.com` API base URL and fails closed on placeholder or
incorrectly prefixed secrets.

Create one Stripe webhook endpoint at:

```text
https://<api-host>/api/billing/webhooks/stripe
```

Subscribe it to Checkout completion, customer subscription lifecycle, invoice
paid, invoice payment failure, invoice payment action required, and invoice
finalization failure events. The endpoint verifies Stripe's signature against
the exact raw request body and enforces the configured replay window.

## Access and evidence controls

- Only a company administrator may create Checkout or portal sessions, after
  re-entering their account password.
- Checkout prices and all redirect/return URLs are selected by the server.
- Only a platform administrator may refund a PaymentIntent, after password
  confirmation and a server-side customer-to-tenant ownership check.
- Every write uses a tenant-scoped client request identifier plus a Stripe
  idempotency key. Reusing an identifier with different content returns a
  conflict.
- Processed lifecycle events and non-lifecycle webhook receipts retain SHA-256
  evidence so exact replays are safe and changed-payload collisions fail.
- These billing records are exported for customer portability as protected
  evidence but cannot be overwritten through controlled restore.

Use distinct Stripe test and live accounts and webhook secrets. Before enabling
live billing, rehearse Checkout, portal return, renewal, failed payment,
cancellation, refund, duplicate delivery, and out-of-order delivery in Stripe
test mode.
