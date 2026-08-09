# ERP/WMS adapter operations

## Scope

OpenPartsFlow provides a safe vendor-neutral connection layer for integrations
whose provider is `erp` or `wms`. The adapter confirms transport and protocol
readiness; customer-specific object, field, workflow, and inventory semantics
remain governed by the integration parity contract and must be validated
against the real external system.

Supported protocols:

- `rest_json`: any HTTPS endpoint where a 2xx response proves connectivity.
- `odata_v4`: HTTPS endpoint where a 2xx response plus OData v4 header,
  `$metadata` marker, or `@odata.context` marker proves protocol compatibility.

Supported authentication:

- none;
- bearer token;
- Basic service-account username and password;
- API key through `X-API-Key`, `API-Key`, `X-Auth-Token`, or `X-API-Token`.

Arbitrary header names are intentionally rejected so an administrator cannot
overwrite `Host`, proxy, forwarding, cookie, or other security-sensitive
headers.

## API and permissions

- `GET /api/integrations/{id}/adapter`: manager/admin read.
- `PUT /api/integrations/{id}/adapter`: administrator save/credential rotation,
  requiring `expected_version` and the current account password.
- `POST /api/integrations/{id}/adapter/test`: administrator connection test,
  requiring the current configuration version and account password.
- `GET /api/integrations/{id}/adapter/tests`: manager/admin evidence history.

Engineers, warehouse users, assistants, API-key callers, inactive integrations,
non-ERP/WMS providers, cross-tenant IDs, and stale versions are rejected.

## Credential protection

Set `INTEGRATION_CREDENTIAL_ENCRYPTION_KEYS` to one or more comma-separated,
URL-safe base64 AES-256 keys. The first key encrypts new credentials; remaining
keys decrypt older credentials during rotation. Keep keys in the deployment
secret manager, never in Git or customer exports.

Generate a key with a trusted secrets tool, for example:

```powershell
$bytes = New-Object byte[] 32
$rng = [Security.Cryptography.RandomNumberGenerator]::Create()
$rng.GetBytes($bytes)
$rng.Dispose()
[Convert]::ToBase64String($bytes)
```

Credentials are encrypted with AES-256-GCM. Authenticated associated data binds
the ciphertext to its organization, integration, authentication type, and
format version. Moving ciphertext between tenants/integrations or tampering
with it fails closed. Reads expose only `has_credentials` and the server-owned
credential update time. Customer export/restore intentionally omits ciphertext.

Rotation procedure:

1. Add the new key first in the environment; retain the previous keys after it.
2. Restart and confirm production configuration readiness.
3. Re-save each credential so new ciphertext uses the first key.
4. Test each current adapter and retain successful evidence.
5. Remove the retired key only after every credential has been re-encrypted.

## Connection validation controls

Before any request, OpenPartsFlow requires HTTPS, disallows embedded
credentials/query/fragments, rejects local hostname suffixes, and rejects
private, loopback, link-local, multicast, reserved, or unspecified literal IPs.
At test time it resolves DNS and applies the same address policy to every
result. The TCP connection is then pinned to a validated public IP while TLS
SNI and certificate verification continue to use the configured hostname,
closing the DNS-rebinding window. Redirects are disabled, timeout is limited to
1–30 seconds and cannot exceed the deployment-wide
`INTEGRATION_CONNECTION_TIMEOUT_SECONDS` cap. Sampled response data is capped by
`INTEGRATION_CONNECTION_MAX_RESPONSE_BYTES`.

Connection tests never store a response body, credential, request header, DNS
answer, raw exception text, or target query. Each append-only evidence row
contains only controlled status/error codes, safe HTTP status, bounded latency,
protocol signal, configuration version, responsible actor/server time, and a
SHA-256 evidence fingerprint. Updating a configuration preserves history but
marks every older result stale.

## Operational acceptance

Before declaring a customer adapter ready:

1. Save the real HTTPS endpoint and least-privilege service credential.
2. Run a successful current-version connection test.
3. Complete the parity contract using the customer's real objects and fields.
4. Verify required read/write directions without granting ownership, completion,
   approval, signature, device, financial, or direct inventory bypass fields.
5. Run parallel reconciliation and have the customer system owner sign off.

A connectivity success alone is not business-semantic acceptance.
