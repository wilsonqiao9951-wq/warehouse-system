# Signed SLA Alert Delivery

OpenPartsFlow can turn aggregate platform-health thresholds into durable,
signed on-call Webhook events. This pipeline is an operational notification
channel; it does not replace an independent synthetic monitor and is not, by
itself, proof of contractual uptime.

## Evidence and state model

The alert worker evaluates the same aggregate risk collector used by Platform
Operations. It never includes organization names, user identities, request
paths, callback URLs, payloads, credentials, exception messages, host names, or
customer records.

`operations_alert_incidents` stores one active episode per alert code. Each
episode retains severity, safe message, current/peak count, observation count,
open/last-observed/resolved server times, and an optimistic version. A partial
unique index prevents concurrent workers from creating two open episodes for
the same code.

The state and event chain is:

```text
threshold breached -> triggered
warning becomes critical -> escalated
still active after configured interval -> reminder
threshold no longer present -> resolved
```

Warnings below `OPERATIONS_ALERT_MIN_SEVERITY` remain visible and durable but
are not sent. If such an episode later reaches the delivery threshold, an
`escalated` event is queued. Resolution is sent only when that episode
previously produced an outbound event.

`operations_alert_deliveries` is a durable outbox. It stores canonical safe
JSON, SHA-256 request evidence, a stable idempotency key, attempt/status, safe
failure code, HTTP status, and timestamps. It never stores a destination
response body or signing secret.

## Receiver contract

Delivery uses HTTPS `POST`, DNS/public-address validation, a TCP connection
pinned to a prevalidated public IP, original-host TLS SNI/certificate
verification, no redirects, a bounded timeout, and bounded response reading.
The following headers accompany canonical JSON:

```text
X-OpenPartsFlow-Operations-Event: triggered|escalated|reminder|resolved|test
X-OpenPartsFlow-Operations-Delivery: <delivery id>
X-OpenPartsFlow-Timestamp: <Unix seconds>
X-OpenPartsFlow-Operations-Signature: sha256=<HMAC hex>
Idempotency-Key: <stable 64-character key>
```

The signature input is `<timestamp>.<raw request body>` and the key is
`OPERATIONS_ALERT_WEBHOOK_SECRET`. Receivers must verify the signature with a
constant-time comparison, reject stale timestamps, and deduplicate the
idempotency key before dispatching to PagerDuty, Opsgenie, Teams, Slack, email,
or another on-call system.

HTTP `2xx` marks an event sent. Network errors, TLS failures, blocked DNS
results, redirects/non-`2xx` responses, and timeouts use controlled failure
codes and retry after 1 minute, 5 minutes, 30 minutes, 2 hours, and 6 hours.
Five failed attempts require a password-confirmed platform-administrator retry.
The stable payload and idempotency key are preserved. A stale `processing`
lease is returned to `pending` only after a bounded safety window.

## Configuration

```text
OPERATIONS_ALERT_DELIVERY_ENABLED=true
OPERATIONS_ALERT_DELIVERY_POLL_SECONDS=60
OPERATIONS_ALERT_WEBHOOK_URL=https://alerts.example.com/openpartsflow
OPERATIONS_ALERT_WEBHOOK_SECRET=<at least 32 random characters>
OPERATIONS_ALERT_MIN_SEVERITY=critical
OPERATIONS_ALERT_REMINDER_MINUTES=60
OPERATIONS_ALERT_REQUEST_TIMEOUT_SECONDS=10
OPERATIONS_ALERT_MAX_RESPONSE_BYTES=4096
```

Staging and production fail closed if alert delivery is enabled with an unsafe
URL, weak/placeholder secret, invalid severity, or out-of-range bounds. The
secret belongs in the deployment secret manager; it is never configured in the
database or returned to the browser.

## Permissions and operation

Only `is_platform_admin=true` can read `/api/platform/operations/alerting`,
queue a signed test, or retry a terminal failure. A customer administrator is
explicitly denied. Test and retry actions require the current account password
and a reason, and create tenant-scoped operator audit entries without recording
the secret, full URL, payload, or response content.

Use `/platform/operations` to review open incidents and delivery evidence.
Before production activation:

1. Configure the external synthetic liveness/readiness probes and independent
   SLA history first.
2. Configure the signed receiver, verify timestamp/signature/idempotency, and
   queue a password-confirmed test event.
3. Cause a controlled threshold breach and confirm `triggered` plus `resolved`
   events reach the on-call system.
4. Return a deliberate non-`2xx`, verify retry evidence, restore the receiver,
   and exercise the protected retry control if the delivery becomes terminal.
5. Document alert ownership, escalation time, and response targets in the
   customer SLA. Keep both external-probe history and OpenPartsFlow incident
   evidence for the acceptance record.
