# Compliance Posture

This is the repository candidate compliance-posture document for January
(SPEC-025, FR-11). It defines the maximum proposed technical statement; it is
not a production compliance declaration and remains subject to operating-owner
and appropriate legal/compliance review. No product surface or documentation
may assert a stronger claim.

SPEC-026 provider cost values are operator-supplied operational estimates with
explicit completeness state. They are not billing, invoices, charges, legal
records, or provider-contract truth and add no compliance certification.

SPEC-027 adds explicit user inspection, correction, deletion, clear, and recall
controls plus bounded private personal context. These are technical product
controls, not consent-management, legal sufficiency, or a compliance claim.

## Alignment claims

The candidate maps implemented technical controls—export, live-state erasure,
retention, audit, and transparency—to concerns commonly addressed by data
protection frameworks such as GDPR, CCPA/CPRA, and LGPD. This mapping is not a
claim of compliance, legal sufficiency, certification, or production approval.

## Roles

- **Controller:** the operating owner is the data controller for the
  deployment.
- **Processor:** January is the data processing software.
- These are product-stated assumptions, not contractual commitments.

## Operating-owner obligations

The following are operating-owner obligations, not product behavior:

- legal basis for processing;
- data processing agreements;
- sub-processor management;
- cross-border transfer mechanisms;
- breach notification;
- supervisory-authority interaction;
- children's-data policy (the product has no age-gating feature).

## Not provided

- No SOC 2 / ISO 27001 / GDPR certification.
- No end-to-end encryption (see the encryption-ownership matrix).
- No legal advice.
- No consent-management system (per-feature opt-in/opt-out controls remain the
  product's control model; a general consent register is future work).

## Boundary of erasure

Erasure covers live product state; backup copies predating an erasure are
governed by the declared backup-retention and purge policy (FR-09).

## Review cadence

The compliance posture and data inventory are reviewed whenever data storage
changes and at least annually by the Product Owner and operating owner.
