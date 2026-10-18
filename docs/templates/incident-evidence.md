# Incident Evidence Template

Metadata-only incident record, consistent with the SPEC-022 evidence-bundle
conventions (SPEC-023 FR-09). Contains no message text, prompts, memories,
vectors, provider bodies, raw platform IDs, usernames, URLs, or credentials.
Every artifact passes the content-safety guard before distribution.

The structured form is produced by
`build_incident_evidence` in
`backend/app/application/observability/incidents.py`.

```json
{
  "evidence_schema_version": 1,
  "artifact": "incident_evidence",
  "environment": "<local|test|staging|production>",
  "severity": "<SEV1|SEV2|SEV3|SEV4>",
  "incident_id": "<opaque incident id>",
  "correlation_id": "<opaque correlation id>",
  "run_id": "<opaque evidence run id>",
  "owners": {
    "operator": "<operator>",
    "incident_contact": "<incident contact>",
    "rollback_authority": "<rollback authority>"
  },
  "timeline": [
    {"phase": "<detection|acknowledgement|classification|response|communication|mitigation|resolution|review>", "at": "<ISO timestamp>", "outcome": "<outcome class>"}
  ],
  "metric_values": {
    "burn_rate": 8.0,
    "quarantine": 60
  },
  "result_classification": "<active|mitigated|resolved|rejected>",
  "recovery_outcome": "<dead_letter_replayed|quarantine_retained|none>",
  "remediation_state": "<open|in_progress|closed>"
}
```

Rules:

- Correlation uses opaque incident/request/correlation IDs only.
- Metric values are bounded content-free numbers.
- Timeline phases are the closed lifecycle set in FR-05.
- Recovery outcome reflects SPEC-016 handling: only one dead letter replayed
  per `operations replay`; quarantined and `delivery_unknown` work is retained.
- Linkage to SPEC-022 live-acceptance evidence and SPEC-021 audit events is by
  opaque identifiers.
