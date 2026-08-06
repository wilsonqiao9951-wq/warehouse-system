# Platform administrator control plane

Platform administrators operate customer organizations. This permission is
separate from an organization's `admin` role.

## Bootstrap

Create a normal administrator account with a password, then promote it from the
project root:

```bash
python -m scripts.promote_platform_admin owner@example.com
```

Promotion is intentionally an operational command rather than a public API.
Restrict shell and database access to trusted platform operators.

## Customer onboarding

Open `/platform` or call `POST /api/platform/organizations`. Creation is atomic
and provisions:

- An organization with Starter, Professional, or Enterprise defaults
- An active subscription or a time-bounded trial
- Its unique slug
- Its first organization administrator
- An Argon2 password hash for the initial administrator password
- An `organization_created` audit event

Normal organization administrators receive `403` from all `/api/platform/*`
endpoints.

## Commercial controls

`PATCH /api/platform/organizations/{id}` can change:

- Platform active/suspended flag
- Commercial plan
- Subscription state
- UTC trial end
- User, main warehouse, and vehicle inventory limits
- AI and external API monthly allowances

Every update must include the current `expected_version`. A stale update returns
`409`; reload the organization before retrying. Plan changes first load the
standard plan defaults and then apply any explicit limits in the same request.

Suspended, cancelled, past-due, inactive, or expired-trial customers cannot start
new sessions. Previously issued tokens and external API keys stop working on
their next request. Platform administrators remain able to enter the control
plane even if their home organization is blocked, so they can restore service.

Commercial updates create `organization_subscription_updated` audit events with
the changed fields, before/after values, actor, authentication method, and
settings version.

See [Commercial branding and plan controls](COMMERCIAL_BRANDING_PLANS.md) for
the default limits, access matrix, capacity rules, and rollout behavior.

## Operational requirements

- Record the customer contract or support ticket associated with creation and suspension.
- Deliver initial passwords through a separate secure channel and require a password change workflow when implemented.
- Use a dedicated named platform account; do not share credentials.
- Protect platform accounts with MFA before general availability.
- Review platform organization audit records against the originating contract,
  support ticket, or approved commercial change.
- Never place passwords, API keys, invitation tokens, or payment details in
  commercial control notes.
