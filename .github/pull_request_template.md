## Scope and reason

Describe the bounded fix or link the agreed product SPEC/design for new behavior.

## Evidence

- Focused tests and affected validator(s):
- `./scripts/validate.sh` and `git diff --check`:
- Broader Quality where appropriate; failures/limitations:

## Review

- [ ] Migration needed? If so, reviewed single-head migration and recovery proof.
- [ ] Documentation/configuration/changelog updated where relevant.
- [ ] Privacy, authority and fail-closed controls preserved; tests use fake I/O.
- [ ] No secrets, private content/account IDs, dumps or unredacted logs included.
- [ ] Applicable third-party notices preserved.

No paid API, live bot, production access or publication is required for a PR.
