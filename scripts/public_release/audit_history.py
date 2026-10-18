"""Bounded, offline, read-only reachable Git review; never publication approval.

Output contains object IDs, path fingerprints and line numbers, never matched
text, identities, filenames or Git stderr. Exact finding dispositions are human
input, not automatic allowlists. See docs/maintainers/public-history-review.md.
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

MAX_OBJECTS = 100_000
MAX_BYTES = 256 * 1024 * 1024
MAX_BLOB_BYTES = 16 * 1024 * 1024
DETECTORS = {
    "telegram-token": r"\b[0-9]{6,12}:[A-Za-z0-9_-]{30,}\b",
    "provider-token": (
        r"\b(?:sk-(?:proj-|or-v1-)?[A-Za-z0-9_-]{20,}|"
        r"gsk_[A-Za-z0-9]{20,}|AIza[A-Za-z0-9_-]{30,}|"
        r"gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|"
        r"AKIA[A-Z0-9]{16})\b"
    ),
    "jwt": r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b",
    "private-key": r"-----BEGIN (?:[A-Z0-9]+ )?PRIVATE KEY-----",
    "credential-url": r"[a-zA-Z][a-zA-Z0-9+.-]*://[^\s/:@]+:[^\s/@]+@",
    "credential-assignment": (
        r"(?i)\b(?:[a-z0-9_]*(?:api_key|bot_token|webhook_secret|"
        r"jwt_secret|database_password|redis_password|secret_access_key)|"
        r"password|secret|access_token|client_secret)"
        r"[\"']?[ \t]*[=:][ \t]*[\"']?[^\s\"'${<>][^\s\"']{5,}"
    ),
    "platform-identifier": (
        r"(?i)\b[a-z_]*(?:chat_id|user_id|external_bot_id)"
        r"[\"']?[ \t]*[=:][ \t]*[\"']?-?[0-9]{5,}"
    ),
    "personal-checkout-path": r"/(?:home|Users)/[^/\s\"'<>]+/",
    "private-record": (
        r"(?i)(?:COPY [^\n]+ FROM stdin;|INSERT INTO [\"']?"
        r"(?:messages|memory_items|participants)|"
        r"\"(?:messages|memories|provider_response|chat_history)\"\s*:\s*[\[{])"
    ),
}
RISKY_PATH = re.compile(
    r"(?i)(?:^|/)(?:\.env(?:\..*)?|id_rsa|[^/]*\.(?:key|pem|p12|pfx|"
    r"sql|dump|log|sqlite3?|db|bak|zip|tar|gz|7z)|[^/]*(?:secret|backup)[^/]*)$"
)
DISPOSITIONS = {
    "synthetic-fixture",
    "documented-example",
    "false-positive",
    "owner-consent-required",
}


class AuditError(Exception):
    """Safe fixed diagnostic, never raw subprocess output."""


def fingerprint(value: str | bytes) -> str:
    if isinstance(value, str):
        value = value.encode("utf-8", "surrogateescape")
    return hashlib.sha256(value).hexdigest()


def git(root: Path, *args: str, data: bytes | None = None) -> bytes:
    # No optional locks, replacements, lazy object downloads, hooks or pager.
    env = {
        **{
            key: value
            for key, value in os.environ.items()
            if not key.startswith("GIT_")
        },
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_NO_LAZY_FETCH": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_PAGER": "cat",
        "LC_ALL": "C",
    }
    try:
        result = subprocess.run(
            ["git", "--no-replace-objects", "-C", str(root), *args],
            input=data,
            capture_output=True,
            env=env,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AuditError("git execution unavailable") from exc
    if result.returncode:
        raise AuditError("git command failed: " + args[0])
    if len(result.stdout) > MAX_BYTES:
        raise AuditError("Git output exceeds review bound")
    return result.stdout


def finding(oid: str, category: str, paths: list[str], lines: list[int]) -> dict:
    identity = json.dumps([oid, category, paths, lines], separators=(",", ":"))
    return {
        "id": fingerprint(identity),
        "object": oid,
        "category": category,
        "path_ids": paths,
        "lines": lines,
        "automatic_detection": True,
        "human_disposition": "unreviewed",
    }


def inspect_content(oid: str, content: bytes, paths: list[str]) -> list[dict]:
    findings = []
    decoded = content.decode("utf-8", errors="replace")
    for category, pattern in DETECTORS.items():
        lines = sorted(
            {
                decoded.count("\n", 0, m.start()) + 1
                for m in re.finditer(pattern, decoded)
            }
        )
        if lines:
            findings.append(finding(oid, category, paths, lines))
    return findings


def _objects(root: Path, oids: list[str]) -> tuple[dict[str, bytes], Counter]:
    request = ("\n".join(oids) + "\n").encode()
    headers = git(root, "cat-file", "--batch-check", data=request).splitlines()
    if len(headers) != len(oids):
        raise AuditError("incomplete object inventory")
    sizes = []
    types = Counter()
    for expected, header in zip(oids, headers, strict=True):
        parts = header.split()
        if (
            len(parts) != 3
            or parts[0].decode() != expected
            or parts[1] not in {b"blob", b"tree", b"commit", b"tag"}
            or not parts[2].isdigit()
        ):
            raise AuditError("unreadable or unsupported reachable object")
        sizes.append(int(parts[2]))
        types[parts[1].decode()] += 1
    if sum(sizes) > MAX_BYTES or max(sizes, default=0) > MAX_BLOB_BYTES:
        raise AuditError(
            "reachable content exceeds review bound; manual review required"
        )
    raw = git(root, "cat-file", "--batch", data=request)
    objects = {}
    cursor = 0
    for oid, size in zip(oids, sizes, strict=True):
        end = raw.find(b"\n", cursor)
        if end < 0 or raw[cursor:end].split()[0].decode() != oid:
            raise AuditError("invalid object stream")
        cursor = end + 1
        objects[oid] = raw[cursor : cursor + size]
        cursor += size
        if raw[cursor : cursor + 1] != b"\n":
            raise AuditError("truncated object stream")
        cursor += 1
    if cursor != len(raw):
        raise AuditError("unexpected object stream suffix")
    return objects, types


def audit(
    root: Path, refs: list[str] | None = None, dispositions: dict | None = None
) -> dict:
    root = root.resolve()
    if (
        Path(git(root, "rev-parse", "--show-toplevel").decode().strip()).resolve()
        != root
    ):
        raise AuditError("source root does not own Git worktree")
    if git(root, "rev-parse", "--is-shallow-repository").strip() != b"false":
        raise AuditError("shallow history cannot establish coverage")
    # Partial clones can fetch implicitly. Refuse them before reading objects.
    config = git(root, "config", "--local", "--list").lower()
    if b"extensions.partialclone=" in config or re.search(
        rb"remote\.[^\n]+\.promisor=(?:true|yes|on|1)(?:\n|$)", config
    ):
        raise AuditError("partial/promisor history is unsupported")
    for name in ("info/grafts", "objects/info/alternates"):
        path = Path(git(root, "rev-parse", "--git-path", name).decode().strip())
        if not path.is_absolute():
            path = root / path
        if path.exists() and path.read_bytes().strip():
            raise AuditError("grafted or alternate history is unsupported")
    rows = (
        git(root, "for-each-ref", "--format=%(refname) %(objectname)")
        .decode()
        .splitlines()
    )
    inventory = dict(row.split(" ", 1) for row in rows)
    if any(name.startswith("refs/replace/") for name in inventory):
        raise AuditError("replacement refs prevent complete history review")
    if not any(name.startswith("refs/heads/") for name in inventory):
        raise AuditError("local branch coverage required")
    selected = sorted(set(refs or [*inventory, "HEAD"]))
    if not set(inventory).issubset(selected) or "HEAD" not in selected:
        raise AuditError("insufficient ref coverage; include all refs and HEAD")
    if set(selected) - {*inventory, "HEAD"}:
        raise AuditError("unknown ref requested")
    if len(selected) > 4096:
        raise AuditError("ref inventory exceeds bound")
    for ref in selected:
        git(root, "rev-parse", "--verify", ref + "^{commit}")
    commits = git(root, "rev-list", *selected, "--").decode().splitlines()
    if not commits:
        raise AuditError("no reachable commits")
    objects_list = (
        git(root, "rev-list", "--objects", "--no-object-names", *selected, "--")
        .decode()
        .splitlines()
    )
    oids = sorted(set(objects_list))
    if len(oids) > MAX_OBJECTS:
        raise AuditError("object inventory exceeds bound")
    all_commits = set(
        git(root, "rev-list", "--all", "HEAD", "--").decode().splitlines()
    )
    if set(commits) != all_commits:
        raise AuditError("all-ref commit coverage mismatch")
    objects, types = _objects(root, oids)
    historical = set()
    blob_paths = defaultdict(set)
    head_paths = set()
    head = git(root, "rev-parse", "HEAD").decode().strip()
    for commit in sorted(commits):
        for entry in git(root, "ls-tree", "-rz", "--full-tree", commit).split(b"\0"):
            if not entry:
                continue
            meta, path = entry.split(b"\t", 1)
            mode, kind, oid = meta.split()
            if kind != b"blob" or mode not in {b"100644", b"100755", b"120000"}:
                raise AuditError("uninspected submodule or unsupported tree entry")
            if oid.decode() not in objects:
                raise AuditError("tree references an uninspected object")
            historical.add(path)
            blob_paths[oid.decode()].add(path)
            if commit == head:
                head_paths.add(path)
    findings = []
    binaries = []
    largest = []
    if len(blob_paths) != types["blob"]:
        raise AuditError("unmapped reachable blobs require explicit review")
    for oid, paths in sorted(blob_paths.items()):
        content = objects[oid]
        path_ids = sorted(fingerprint(path) for path in paths)
        findings.extend(inspect_content(oid, content, path_ids))
        risky = sorted(
            fingerprint(p)
            for p in paths
            if RISKY_PATH.search(p.decode("utf-8", "replace"))
        )
        if risky:
            findings.append(finding(oid, "high-risk-path", risky, []))
        try:
            content.decode("utf-8")
            binary = b"\0" in content
        except UnicodeDecodeError:
            binary = True
        if binary:
            binaries.append(
                {"object": oid, "bytes": len(content), "path_ids": path_ids}
            )
            findings.append(finding(oid, "non-text-review", path_ids, []))
        largest.append({"object": oid, "bytes": len(content), "path_ids": path_ids})
    email_categories = Counter()
    author_names = set()
    committer_names = set()
    dated = []
    signed = 0
    merges = 0
    for oid in sorted(commits):
        content = objects[oid]
        findings.extend(inspect_content(oid, content, []))
        headers = content.split(b"\n\n", 1)[0].splitlines()
        signed += any(line.startswith(b"gpgsig ") for line in headers)
        merges += sum(line.startswith(b"parent ") for line in headers) > 1
        for role, names in (
            (b"author ", author_names),
            (b"committer ", committer_names),
        ):
            header = next((h[len(role) :] for h in headers if h.startswith(role)), None)
            if header is None:
                raise AuditError("missing commit identity metadata")
            match = re.fullmatch(rb"(.*) <([^<>]*)> ([0-9]+) [+-][0-9]{4}", header)
            if match is None:
                raise AuditError("unparseable commit identity metadata")
            name, email, timestamp = match.groups()
            names.add(fingerprint(name))
            email_categories[
                "github-noreply"
                if email.endswith(b"@users.noreply.github.com")
                else "other-email-owner-review"
            ] += 1
            if role == b"committer ":
                dated.append((int(timestamp), oid))
    dispositions = dispositions or {}
    known = {f["id"] for f in findings}
    if set(dispositions) - known:
        raise AuditError("stale or unknown human disposition")
    for item in findings:
        entry = dispositions.get(item["id"])
        if entry is not None:
            if (
                not isinstance(entry, dict)
                or entry.get("disposition") not in DISPOSITIONS
                or not isinstance(entry.get("reason"), str)
                or not entry["reason"].strip()
                or (
                    entry["disposition"] == "owner-consent-required"
                    and item["category"] != "personal-checkout-path"
                )
            ):
                raise AuditError("invalid human disposition")
            item["human_disposition"] = entry["disposition"]
    unresolved = sum(f["human_disposition"] == "unreviewed" for f in findings)
    first, last = min(dated), max(dated)
    return {
        "schema": 1,
        "status": "REVIEW_REQUIRED"
        if unresolved
        else "NO_UNRESOLVED_AUTOMATIC_FINDINGS",
        "publication_approval": False,
        "coverage": {
            "refs": [
                {"ref_id": fingerprint(r), "object": inventory.get(r, head)}
                for r in selected
            ],
            "all_local_refs_and_HEAD": True,
            "network": False,
            "commits": len(commits),
            "merges": merges,
            "objects": len(oids),
            "object_types": dict(sorted(types.items())),
            "historical_paths": len(historical),
            "deleted_paths": len(historical - head_paths),
            "historical_path_ids": sorted(fingerprint(p) for p in historical),
            "deleted_path_ids": sorted(fingerprint(p) for p in historical - head_paths),
            "earliest_committer": {
                "commit": first[1],
                "utc": datetime.fromtimestamp(first[0], UTC).isoformat(),
            },
            "latest_committer": {
                "commit": last[1],
                "utc": datetime.fromtimestamp(last[0], UTC).isoformat(),
            },
            "content_bytes": sum(map(len, objects.values())),
        },
        "metadata": {
            "distinct_author_names": len(author_names),
            "distinct_committer_names": len(committer_names),
            "email_header_categories": dict(sorted(email_categories.items())),
            "signature_headers_present": signed,
            "unsigned_commits": len(commits) - signed,
            "signature_verification": (
                "not performed; unsigned is not a security failure"
            ),
            "owner_gate": (
                "OWNER REVIEW REQUIRED — GIT COMMIT METADATA AND PERSONAL PATHS"
            ),
        },
        "detectors": sorted(DETECTORS),
        "findings": sorted(findings, key=lambda f: f["id"]),
        "unresolved": unresolved,
        "non_text_blobs": binaries,
        "largest_blobs": sorted(largest, key=lambda b: (-b["bytes"], b["object"]))[:20],
        "limitations": [
            "Heuristics cannot prove absence of every secret or private record.",
            "Human dispositions are exact-object review inputs, not scanner approvals.",
            "Unreachable objects, reflogs and uninspected remote surfaces excluded.",
            "No signature verification; owner consent and independent audit required.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--ref", action="append")
    parser.add_argument("--dispositions", type=Path)
    args = parser.parse_args()
    try:
        dispositions = (
            json.loads(args.dispositions.read_text()) if args.dispositions else None
        )
        if dispositions is not None and not isinstance(dispositions, dict):
            raise AuditError("human dispositions must be an object")
        result = audit(args.root, args.ref, dispositions)
    except (AuditError, OSError, ValueError, KeyError, IndexError) as exc:
        # Only fixed AuditError diagnostics are safe to emit.
        reason = (
            str(exc)
            if isinstance(exc, AuditError)
            else "unreadable or invalid review input"
        )
        print(
            json.dumps(
                {
                    "status": "COVERAGE_INCOMPLETE",
                    "reason": reason,
                    "publication_approval": False,
                },
                sort_keys=True,
            )
        )
        return 2
    print(json.dumps(result, sort_keys=True, indent=2))
    return 1 if result["unresolved"] else 0


if __name__ == "__main__":
    sys.exit(main())
