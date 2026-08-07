# Authentication rollout

OpenPartsFlow supports email/password login with Argon2 password hashes and expiring JWT sessions. The production same-origin web application requests an HttpOnly Cookie session; standalone API, development, and mobile clients may continue to request a Bearer response explicitly.

Engineer sessions are also bound to a registered device. The mobile client creates a stable random device ID and a 256-bit device secret. The API stores only the secret hash and includes the device ID in the JWT. Every device-bound request must present the session (Cookie or Bearer) and `X-Device-Token`.

## Browser Cookie sessions and API compatibility

The login endpoints accept an explicit mode header:

```text
X-Session-Mode: cookie
X-Session-Mode: bearer
```

Cookie mode never returns the JWT in the response body. In production and staging it sets `__Host-opf_session` with `Secure`, `HttpOnly`, `SameSite=Strict`, no `Domain`, and `Path=/`; the Cookie lifetime matches the access-token lifetime. The response returns only a random CSRF proof. Its SHA-256 digest is signed into that specific JWT, and every Cookie-authenticated `POST`, `PUT`, `PATCH`, or `DELETE` must send the value as `X-CSRF-Token`. A proof from another login session is rejected. The frontend may retain this non-authenticating proof locally, but the credential itself is inaccessible to JavaScript.

The web client defaults `NEXT_PUBLIC_AUTH_SESSION_MODE=auto`: a secure same-origin `/api` deployment selects Cookie mode, while the separate HTTP development API and standalone clients retain Bearer mode. Set the value explicitly to `cookie` or `bearer` only for a reviewed deployment. All browser requests include credentials; engineer Cookie sessions continue to require the registered device secret and active work-order claim generation.

`POST /api/auth/logout` validates the session-bound CSRF proof before expiring the Cookie. Password-confirmed session revocation and MFA operations that rotate the authentication version also expire the browser Cookie in their response. Supplying an Authorization Bearer header takes precedence over an incidental Cookie and preserves backward-compatible non-browser API behavior without CSRF headers.

## Production settings

```text
RBAC_ENFORCE=true
LEGACY_HEADER_AUTH=false
JWT_SECRET_KEY=<at least 32 random bytes, supplied by secret management>
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=480
LOGIN_RATE_LIMIT_WINDOW_SECONDS=900
LOGIN_RATE_LIMIT_PRINCIPAL_FAILURES=10
LOGIN_RATE_LIMIT_SOURCE_FAILURES=50
PASSWORD_RESET_EXPIRE_MINUTES=30
PASSWORD_RESET_RATE_LIMIT_WINDOW_SECONDS=3600
PASSWORD_RESET_PRINCIPAL_REQUESTS=3
PASSWORD_RESET_SOURCE_REQUESTS=20
MFA_ENCRYPTION_KEYS=<one or more comma-separated base64 AES-256 keys, newest first>
MFA_CHALLENGE_EXPIRE_MINUTES=5
MFA_ENROLLMENT_EXPIRE_MINUTES=10
MFA_MAX_ATTEMPTS=5
PASSWORD_RESET_EMAIL_ENABLED=true
INVITATION_EMAIL_ENABLED=true
AUTH_EMAIL_FROM=OpenPartsFlow <security@example.com>
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USERNAME=<relay account>
SMTP_PASSWORD=<relay secret>
SMTP_USE_STARTTLS=true
SMTP_USE_SSL=false
SMTP_TIMEOUT_SECONDS=10
```

The application refuses to issue tokens in staging or production when the development JWT secret is still configured.

## Login abuse protection and session revocation

Login failures are rate limited in a durable database window by both the normalized account identifier and the request's authenticated network peer. The default policy blocks after 10 account failures or 50 source failures in 15 minutes and returns `429` with `Retry-After`. Application code never parses client-supplied forwarding headers. The production Compose topology lets Uvicorn accept the Nginx-provided peer address only inside the isolated, unpublished API network; direct deployments must configure an equivalently trusted proxy boundary before enabling forwarded-header processing.

Every login result is retained as a security event. Account identifiers and network sources are stored only as keyed SHA-256 fingerprints derived from the server JWT secret. The event record never contains a raw email address, IP address, password, bearer token, device secret, or submitted credential. Administrators may inspect safe tenant-only outcomes through:

```text
GET /api/auth/security-events
```

Every access token carries the user's current authentication version. An administrator password change increments that version, so every previously issued token stops working immediately. Any signed-in user can re-enter their current password and revoke all sessions through:

```text
POST /api/auth/sessions/revoke-all
```

The profile workspace exposes this control to every role and shows the tenant-scoped event history to administrators. Device registrations are not silently deleted by session revocation; users must authenticate again, and the existing device-secret checks still apply.

## Password reset

The public reset workflow uses three endpoints:

```text
GET  /api/auth/password-reset/configuration
POST /api/auth/password-reset/request
POST /api/auth/password-reset/complete
```

Production and staging expose reset requests only when the SMTP relay, sender, TLS mode, credential pairing, port, and timeout pass startup validation. Account lookup responses are identical for known, unknown, disabled, and ineligible users. Requests are bounded by keyed account and trusted-source fingerprints; once the limit is reached, the API keeps returning the same accepted response without creating additional tokens or delivery work.

Each eligible request invalidates earlier unused tokens and creates 32 random bytes. Only the keyed token hash is stored. Tokens expire after 30 minutes by default, are consumed through a conditional database update, and cannot be replayed. Completing a reset replaces the Argon2 password hash, increments the account authentication version, invalidates every older Cookie or Bearer session, and records safe security evidence.

SMTP delivery runs after the HTTP response so account existence cannot be inferred from relay latency. The raw token exists only in the reset URL passed to the mail task and is never written to the database, logs, API response, or customer export in production. Delivery status retains only `pending`, `sent`, or a safe failure code; a user can request another link after a relay failure. Development/test mode may expose a clearly labeled local reset URL when email delivery is disabled.

## Verified employee invitations

Production and staging invitations require `INVITATION_EMAIL_ENABLED=true` and the same validated TLS SMTP transport used by password reset. If delivery is disabled or misconfigured, `POST /api/users/invitations` fails before creating an invitation. The administrator response never contains the sign-up URL; only the invited mailbox receives the random single-use capability. Development and test environments may return a clearly labeled manual URL when invitation email is disabled.

Only SHA-256 token hashes are stored. Each invitation retains `manual`, `pending`, `sent`, or `failed` delivery status, attempt count, safe failure code, and delivery timestamps without retaining the raw token. Reissuing an invitation invalidates only unused invitations for the same normalized email inside the administrator's organization; it cannot affect another tenant using the same address. Creation is tenant-audited without storing the email or token in audit metadata.

## Administrator multi-factor authentication

Organization and platform administrators can opt into RFC 6238 TOTP from the Profile workspace. Engineer, warehouse, manager, and assistant accounts cannot enroll through the administrator MFA endpoints. Enrollment requires the current account password, returns the provisioning secret only during the short enrollment window, and is not active until a valid authenticator code is confirmed.

```text
GET  /api/auth/mfa/status
POST /api/auth/mfa/enrollment/start
POST /api/auth/mfa/enrollment/confirm
POST /api/auth/mfa/login/complete
POST /api/auth/mfa/recovery-codes/regenerate
POST /api/auth/mfa/disable
```

TOTP uses a 30-second period, six digits, HMAC-SHA1 interoperability, and at most one time step of clock drift. The server records the last accepted step and conditionally advances it, so the same authenticator code cannot be replayed. Password verification succeeds before the API returns a five-minute MFA challenge; that challenge omits the access-token authentication-version claim and cannot be used as a Bearer session. Invalid codes are rate limited by both keyed account and direct-peer fingerprints.

The per-user TOTP secret is encrypted at rest with versioned AES-256-GCM authenticated encryption and bound associated data. `MFA_ENCRYPTION_KEYS` is mandatory in staging and production. Put the newest key first; encryption uses it while decryption tries every configured key so operators can rotate secrets without an outage. Losing every configured key makes enrolled secrets unrecoverable. Generate a key with:

```text
python -c "import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
```

Ten high-entropy one-time recovery codes are displayed only after enrollment or explicit regeneration. Only SHA-256 digests are stored, and consumption is conditional so concurrent reuse is rejected. Enabling or disabling MFA and replacing recovery codes increments the account authentication version, immediately revoking older browser and phone sessions. TOTP secrets, recovery digests, accepted steps, passwords, challenges, and recovery values are excluded from customer exports and safe authentication-event projections.

## Account onboarding

New users may be created with a password by an organization administrator. Existing migrated users have no password hash and cannot log in until an administrator calls:

```text
POST /api/users/{user_id}/set-password
```

Passwords are never returned by the API or stored in plaintext. Disabled users cannot log in and existing tokens stop working immediately because account status is checked on every authenticated request.

## Engineer device and work-order binding

The login client sends:

```text
X-Device-Id: <stable random device id>
X-Device-Token: <high-entropy device secret>
X-Device-Name: <human-readable phone/browser name>
```

Work-order execution uses a server-owned claim containing the engineer, registered device, claim time, and monotonically increasing claim version. Execution writes additionally send `X-Claim-Version`. A request is rejected unless all three values still match the active claim.

Claim and completion are online-only operations. Completion requires the current account password again; the password is verified and discarded, never stored in work-order or audit data.

Managers may approve completion or release a claim with a reason, but cannot edit field records. Administrators may correct unlocked field records with their own audit attribution, but cannot request or directly complete a job as if they were the engineer. The immutable completion attribution remains the claiming engineer and device.

Fault type, error code, environment, final outcome, first-time-fix, and rework evidence follow the same owner-only field-write rules. They freeze while completion approval is pending and become immutable when the work order is locked. Repair duration is calculated by the server from the recorded start and engineer completion-submission times; clients cannot submit it.

## Engineer vehicle-receipt authentication

Vehicle replenishment receipt uses the same registered-device session with an additional password step-up. A successful `receive` action requires all of the following at the same time:

- the authenticated account has the exact engineer role;
- the replenishment `target_user_id` matches the authenticated user;
- the Cookie or Bearer JWT names an active registered device and `X-Device-Token` proves possession of that device secret;
- the destination van remains assigned to the same engineer;
- `account_password` verifies against the current account password;
- the replenishment is still `shipped` at the supplied `expected_version`.

The server records `received_by`, `received_device_id`, and `received_at`, then posts the vehicle `INBOUND` inventory movement in the same transaction. Passwords and raw device secrets are never stored in custody or audit data.

Managers and administrators approve or reject replenishment requests before custody begins; rejection requires a reason. Managers cannot pick, ship, receive, complete, or cancel. Warehouse users cannot approve their own queue and may only begin picking after approval. Warehouse users and administrators perform later custody actions, but cannot receive a delivery assigned to an engineer's van.

Legacy custody rows marked `requires_reconciliation` reject every normal workflow action. Only an administrator may reconcile one through the dedicated endpoint, using a reason, matching version, and current administrator password. A row with linked inventory movements cannot use the historical reconciliation path. The password is verified and discarded exactly like the engineer receipt password.

Manual replenishment creation requires a client-generated `client_request_id` and business reason. The ID provides organization-scoped retry idempotency; it is not an authentication credential and never replaces session/device authorization.

Vehicle returns follow the inverse custody rule. Only the vehicle owner on a registered device may create the request or confirm handover. Handover requires the current account password and records the engineer plus device before vehicle stock is deducted. Warehouse/admin users may approve and receive, but cannot impersonate the engineer handover.

Inventory counts separate observation from authority. Warehouse users may record and submit physical quantities, but only an administrator who re-enters their current password can approve discrepancies and create linked adjustment transactions.

Notification/manual request creation, picking, shipping, receipt, completion, cancellation, and reconciliation are online-only. The frontend never writes these operations or either password step-up to its offline queue.

## Legacy identity headers

The application is fail-closed in every runnable environment: RBAC is enabled and `X-User-Id` authentication is disabled even when an older local `.env` still contains pilot values. Tests may opt into an in-memory legacy actor only inside the isolated test fixture. The production frontend contains no legacy identity fallback.
