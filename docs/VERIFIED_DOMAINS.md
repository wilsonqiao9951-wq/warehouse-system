# Verified custom domains and customer sender identities

This Phase 9 control lets a Professional or Enterprise customer prove control
of one public hostname, use that hostname for automatic login branding, and
reserve a customer-specific sender address. Starter organizations receive
`403` and verified domains stop resolving publicly if the organization is
downgraded to Starter or suspended at the platform level.

## Ownership workflow

An organization administrator enters a hostname only, such as
`service.company.com`. Schemes, ports, paths, IP addresses, local names, and
reserved test namespaces are rejected. Unicode hostnames are stored in canonical
lowercase IDNA form and the hostname is globally unique across customers.

OpenPartsFlow generates a high-entropy TXT challenge:

```text
Type:  TXT
Name:  _openpartsflow-challenge.service.company.com
Value: openpartsflow-verification=<random challenge>
```

After the customer publishes the record, `POST /api/organization/domain/verify`
queries the operator-configured fixed DNS-over-HTTPS resolver. It does not fetch
the customer hostname and never accepts a verification URL from the request.
The default resolver is Cloudflare's documented
[`https://cloudflare-dns.com/dns-query`](https://developers.cloudflare.com/1.1.1.1/encryption/dns-over-https/make-api-requests/).

Failed checks remain pending and return a safe error in the domain record.
Checks are rate-limited by `CUSTOM_DOMAIN_VERIFICATION_COOLDOWN_SECONDS`
(default 30). DNS responses are used only for an exact, constant-time challenge
comparison and are not written to the database or audit log.

Rotating the challenge immediately invalidates the previous proof, returns the
domain to pending, and disables its sender identity. Changing the hostname has
the same effect. Every mutation uses an optimistic `version`; stale requests
return `409`. Configuring or changing a hostname, rotating its proof, changing
its sender identity, and removing it also require the administrator's current
account password. DNS checks do not require the password and never store it.

## Branded login resolution

Once verified, the safe public endpoint resolves branding by hostname:

```http
GET /api/auth/organization-branding/by-domain/service.company.com
```

The login page calls this endpoint automatically for non-local browser hosts.
The response contains the same safe branding fields as the slug-based login and
never exposes the DNS challenge, plan, subscription, users, usage, or sender
configuration.

Ownership verification does not provision DNS routing, TLS certificates, a
reverse proxy, or hosting. Operations must still route the verified hostname to
the frontend, issue a certificate, add the origin to `CORS_EXTRA_ORIGINS`, and
ensure `NEXT_PUBLIC_API_BASE_URL` points to the public HTTPS API.

## Customer sender identity

After ownership is verified, an organization administrator can reserve a safe
display name and local part such as:

```text
ACME Service Dispatch <dispatch@service.company.com>
```

Line breaks, blank names, invalid local parts, and consecutive dots are
rejected. The address is disabled automatically if its proof is rotated or its
hostname changes.

This batch establishes verified ownership and the tenant sender configuration;
it does not send email or claim SPF/DKIM/provider delivery verification. An
outbound email provider and its required DNS authentication records must be
connected before customer messages are delivered.

## API

All organization management endpoints require an organization administrator:

```text
GET    /api/organization/domain
PUT    /api/organization/domain
POST   /api/organization/domain/verify
POST   /api/organization/domain/rotate-challenge
PATCH  /api/organization/domain/email-identity
DELETE /api/organization/domain
```

The settings UI displays the exact DNS record, propagation status, last check,
verified login link, challenge rotation, sender configuration, and removal.
Platform customer rows display domain, verification state, and active sender
address without exposing the challenge.

## Security and audit

- One global hostname can belong to only one organization.
- The existing tenant read/write filter covers domain records.
- Only administrators can read the challenge or mutate domain/email settings.
- Sensitive mutations require Bearer authentication plus current-password
  reauthentication; passwords are never stored in payload or audit metadata.
- The public lookup returns branding only for a verified, active,
  Professional/Enterprise organization.
- DNS verification uses a fixed operator URL, HTTPS, no embedded credentials,
  no redirects, a five-second timeout, and exact TXT comparison.
- Audit records contain domain, outcome, availability flag, and version, never
  the challenge value or DNS response contents.
- Migration `20260806_0034` refuses downgrade while any domain configuration
  exists.
