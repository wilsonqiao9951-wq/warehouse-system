# Platform administrator control plane

Platform administrators operate customer organizations. This permission is separate from an organization's `admin` role.

## Bootstrap

Create a normal administrator account with a password, then promote it from the project root:

```bash
python -m scripts.promote_platform_admin owner@example.com
```

Promotion is intentionally an operational command rather than a public API. Restrict shell and database access to trusted platform operators.

## Customer onboarding

Open `/platform` or call `POST /api/platform/organizations`. Creation is atomic and provisions:

- An active organization
- Its unique slug
- Its first organization administrator
- An Argon2 password hash for the initial administrator password

Normal organization administrators receive `403` from all `/api/platform/*` endpoints.

## Suspension

`PATCH /api/platform/organizations/{id}` changes `is_active`. Suspended customer users cannot start new sessions, and previously issued access tokens stop working on their next request. Platform administrators remain able to enter the control plane even if their home organization is suspended, so they can restore service.

## Operational requirements

- Record the customer contract or support ticket associated with creation and suspension.
- Deliver initial passwords through a separate secure channel and require a password change workflow when implemented.
- Use a dedicated named platform account; do not share credentials.
- Protect platform accounts with MFA before general availability.
- Audit all platform actions in the next hardening phase.
