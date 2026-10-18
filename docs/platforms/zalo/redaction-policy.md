# Zalo Verification Redaction Policy

## Boundary

Raw responses, webhook bodies, headers, credentials, authorization codes,
cookies, phone numbers, and real identifiers belong only in
`.local/zalo-verification/` or an operator-managed temporary location. Neither
path is tracked. Delete raw evidence when the operator no longer needs it.

Tracked evidence uses aliases only: `OA-A`, `APP-A`, `USER-A`, `USER-B`,
`GMF-A`, `MSG-IN-001`, and `MSG-OUT-001`.

## Allowed Tracked Values

- field name and data type;
- presence/absence and stable-vs-changing observation;
- a short one-way fingerprint when necessary, never the source value;
- HTTP status, official error code, rounded timestamp, and retry count;
- the fixed synthetic strings `january-zalo-verification-inbound-001` and
  `january-zalo-verification-outbound-001` only.

## Prohibited Tracked Values

- access/refresh tokens, application secret, authorization code, cookie, or
  request signature;
- full OA, group, user, message, or callback IDs;
- real names, phone numbers, production data, or unbounded webhook payloads;
- customer-generated text or screenshots containing identifiers.

Before a report or commit candidate, run
`./scripts/validate-zalo-verification.sh`; it scans tracked verification
artifacts and rejects credential-like values.
