# Authentication rollout

OpenPartsFlow supports email/password login with Argon2 password hashes and expiring Bearer JWT access tokens.

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

## Temporary legacy mode

`LEGACY_HEADER_AUTH=true` permits the pilot-only `X-User-Id` flow when RBAC is enabled. This exists only for controlled migration and must be disabled before customer production use.

## Remaining commercial hardening

- Password reset with single-use, short-lived tokens
- Refresh-token rotation or secure server-managed sessions
- Login rate limiting and security event logging
- Optional MFA for administrators
- Prefer HttpOnly secure cookies for browser deployments that do not require standalone Bearer-token clients
- Organization invitation and email verification workflow
