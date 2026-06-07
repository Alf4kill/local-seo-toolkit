#!/usr/bin/env python3
"""
check_secrets.py - local, zero-dependency secret scanner (stdlib only).

Blocks credentials / API keys from being committed to this repository.

Modes:
    python scripts/check_secrets.py --staged   # scan files staged for commit (pre-commit)
    python scripts/check_secrets.py --all      # scan the whole tracked + untracked tree

Wire it up via .pre-commit-config.yaml, or install as a native git hook:
    cp scripts/check_secrets.py .git/hooks/pre-commit

Exit code 0 = clean, 1 = secret found (commit blocked).
"""
import os
import re
import subprocess
import sys

# Files whose mere presence in a commit is forbidden (real credential files).
BLOCKED_BASENAMES = {
    "client_secrets.json", "token.json", "credentials.json",
    "google_api_key.txt", ".env", "id_rsa",
}
BLOCKED_SUFFIXES = (".pem", ".key", ".p12", ".pfx")

# Content patterns that look like real secrets.
PATTERNS = [
    ("Google API key",          re.compile(r"AIza[0-9A-Za-z_\-]{35}")),
    ("Google OAuth token",      re.compile(r"ya29\.[0-9A-Za-z_\-]{20,}")),
    ("OAuth client_secret",     re.compile(r"\"client_secret\"\s*:\s*\"[A-Za-z0-9_\-]{12,}\"")),
    ("Private key block",       re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----")),
    ("GitHub token",            re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[0-9A-Za-z]{30,}\b")),
    ("GitHub fine-grained PAT", re.compile(r"\bgithub_pat_[0-9A-Za-z_]{20,}\b")),
    ("AWS access key id",       re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("Slack token",             re.compile(r"\bxox[baprs]-[0-9A-Za-z\-]{10,}\b")),
    ("Generic sk- key",         re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
]

# Paths excluded from the CONTENT scan: they legitimately contain the patterns
# above (as documentation / placeholders) and would otherwise self-trigger.
CONTENT_SKIP = {
    "scripts/check_secrets.py",
    "SECURITY.md",
    ".pre-commit-config.yaml",
}
SKIP_SUFFIXES = (".example",)
BINARY_SUFFIXES = (
    ".png", ".jpg", ".jpeg", ".gif", ".pdf", ".docx", ".xlsx",
    ".zip", ".rar", ".npy", ".ico", ".woff", ".woff2", ".ttf",
)


def _run(cmd):
    out = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    return [ln for ln in out.stdout.splitlines() if ln.strip()]


def staged_files():
    return _run(["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"])


def all_files():
    tracked = _run(["git", "ls-files"])
    untracked = _run(["git", "ls-files", "--others", "--exclude-standard"])
    return sorted(set(tracked) | set(untracked))


def _skip_content(path):
    p = path.replace("\\", "/")
    return (
        p in CONTENT_SKIP
        or p.endswith(SKIP_SUFFIXES)
        or p.lower().endswith(BINARY_SUFFIXES)
    )


def scan(paths):
    findings = []
    for path in paths:
        base = os.path.basename(path)
        if base in BLOCKED_BASENAMES or path.lower().endswith(BLOCKED_SUFFIXES):
            findings.append((path, 0, "Forbidden credential file", base))
            continue
        if _skip_content(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except (OSError, UnicodeDecodeError):
            continue  # missing or binary
        for i, line in enumerate(lines, 1):
            for label, rx in PATTERNS:
                if rx.search(line):
                    findings.append((path, i, label, line.strip()[:80]))
    return findings


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "--staged"
    paths = all_files() if mode == "--all" else staged_files()
    if not paths:
        print("[check-secrets] nothing to scan.")
        return 0
    findings = scan(paths)
    if not findings:
        print(f"[check-secrets] OK - scanned {len(paths)} file(s), no secrets found.")
        return 0
    print("\n[check-secrets] BLOCKED - potential secrets detected:\n")
    for path, line, label, snippet in findings:
        loc = f"{path}:{line}" if line else path
        print(f"  x {label}\n      {loc}\n      {snippet}\n")
    print("Remove the secret (or git-ignore the file) and try again.")
    print("False positive? Add the path to CONTENT_SKIP in scripts/check_secrets.py.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
