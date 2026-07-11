# Authentication rollout

OpenPartsFlow supports email/password login with Argon2 password hashes and expiring Bearer JWT access tokens.

Engineer sessions are also bound to a registered device. The mobile client creates a stable random device ID and a 256-bit device secret. The API stores only the secret hash and includes the device ID in the JWT. Every device-bound request must present both the Bearer token and `X-Device-Token`.

## Production settings

```text
RBAC_ENFORCE=true
LEGACY_HEADER_AUTH=false
JWT_SECRET_KEY=<at least 32 random bytes, supplied by secret management>
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=480
```

The application refuses to issue tokens in staging or production when the development JWT secret is still configured.

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

## Legacy identity headers

The application is fail-closed in every runnable environment: RBAC is enabled and `X-User-Id` authentication is disabled even when an older local `.env` still contains pilot values. Tests may opt into an in-memory legacy actor only inside the isolated test fixture. The production frontend contains no legacy identity fallback.

## Remaining commercial hardening

- Password reset with single-use, short-lived tokens
- Refresh-token rotation or secure server-managed sessions
- Login rate limiting and security event logging
- Optional MFA for administrators
- Prefer HttpOnly secure cookies for browser deployments that do not require standalone Bearer-token clients
- Organization invitation and email verification workflow
