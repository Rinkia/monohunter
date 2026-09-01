# Security Policy

## Scope

monohunter is a command-line / batch tool: it reads public TESS data from MAST and other
astronomical archives, runs analysis locally, and writes JSON/PNG/CSV outputs. It exposes
**no network service** and stores **no secrets**. The realistic risk surface is:

- **Untrusted data files** — candidate/contribution/follow-up JSON records and (in the
  community leaderboard) contributor-submitted fields. These are validated with Pydantic
  (`extra="forbid"`) and HTML-escaped before rendering.
- **Model files** — the triage model is serialized as plain-float **JSON** (not pickle),
  so loading one cannot execute code. Only load model files you trust regardless.
- **The Docker image** — runs as a non-root user (uid 10001) with only its data volume.

## Reporting a vulnerability

Please **do not** open a public issue for a security problem. Instead use GitHub's
private vulnerability reporting: **Security → Report a vulnerability** on
<https://github.com/Rinkia/monohunter>, or open a
[GitHub Security Advisory](https://github.com/Rinkia/monohunter/security/advisories/new).

Include what you did, what happened, and (if known) the affected version. We aim to
acknowledge within a few days and to fix confirmed issues in a patch release.

## Good practice for operators

- Load only triage model files and contribution data you trust.
- Run the container as published (non-root); prefer a named volume over a bind mount.
- Keep dependencies current (`pip install -U monohunter`).
