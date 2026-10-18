# Post-Incident Review Template

Required for every Sev1/Sev2 incident (SPEC-023 FR-10). Metadata-only;
contains no message content, prompts, memories, vectors, provider bodies, or
credentials. Produced by `build_post_incident_review` in
`backend/app/application/observability/incidents.py`.

```json
{
  "artifact": "post_incident_review",
  "incident_id": "<opaque incident id>",
  "severity": "<SEV1|SEV2>",
  "timeline": [
    {"phase": "<closed lifecycle phase>", "at": "<ISO timestamp>", "outcome": "<outcome class>"}
  ],
  "root_cause_class": "<provider_outage|dependency_outage|capacity_exhaustion|deployment_rollout|configuration_error|secret_rotation|recovery_backlog|alerting_failure|unknown>",
  "error_budget_impact": "<fraction of the 28-day budget consumed and the affected SLI>",
  "corrective_actions": ["<action>"],
  "remediation_owner": "<owner>"
}
```

Rules:

- Root-cause class is a closed set; unknown is allowed rather than fabrication.
- Error-budget impact is expressed as a fraction of the rolling 28-day budget
  for the affected SLI, computed from the exported catalog.
- Corrective actions are tracked to closure and fed back into SLO targets,
  alert thresholds, and runbooks.
- Content-safety review gate runs before distribution.
