# 0008 Operator Demo Boundary

Date: 2026-07-29

## Status

Accepted

## Decision

Use a local, polling-only, explicitly confirmed demo mode with an allowlist of
dedicated Telegram chat IDs. Bootstrap persists only a credential reference and
safe bot metadata. Workers remain independent processes; the API does not own
orchestrated background work.

## Consequences

Live verification is deliberate and limited to dedicated chats. Updates outside
the allowlist are durably ignored before product state exists. This is a local
operator workflow, not a deployment or production control plane.
