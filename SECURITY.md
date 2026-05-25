# Security Policy

## Supported versions

Only the latest `1.3.x` line of Enterprise MCP Server receives security fixes. Older
releases are not supported — please upgrade.

| Version | Supported          |
|---------|--------------------|
| 1.3.x   | Yes                |
| < 1.3   | No                 |

This table will be updated as the support window changes.

## Reporting a vulnerability

**Please do not open a public GitHub issue for security vulnerabilities.**

Preferred reporting channel:

- **GitHub Security Advisories** — open a private advisory at
  `https://github.com/nonagenticai/enterprise_mcp_server/security/advisories/new`. This
  keeps the discussion private until a fix is ready.

If you cannot use GitHub Security Advisories (for example, you don't have a GitHub
account), open a regular issue titled `Security: please contact me privately` — do
**not** include vulnerability details — and a maintainer will reach out via the email
on your GitHub profile or via GitHub's contact form.

When reporting, please include:

- A clear description of the vulnerability and its impact.
- Steps to reproduce, ideally with a minimal proof of concept.
- Affected version(s) / commit hashes.
- Your suggested severity and any mitigations you've identified.
- Whether you'd like public credit when the advisory is published.

## Response expectations

- **Acknowledgment:** within **5 business days** of receiving your report.
- **Triage and severity assessment:** within **10 business days**.
- **Fix target:** **30 days** for high-severity issues; longer windows may apply for
  lower-severity findings or issues requiring architectural changes.
- **Coordinated disclosure window:** **90 days** from initial report. We will work with
  you on timing if more time is genuinely needed; otherwise we publish at day 90.

## Scope

**In scope:**

- Source code in this repository.
- Default configurations and deployment manifests shipped in this repo (Docker /
  Docker Compose, `init_db.sh`, scripts).
- Documentation that, if followed verbatim, would lead to insecure deployments.

**Out of scope:**

- Third-party services that Enterprise MCP Server integrates with (report to those
  vendors directly).
- Any specific deployment of Enterprise MCP Server operated by the author or a third
  party — only the upstream code is in scope here.
- Findings that require physical access to a machine, social engineering of maintainers,
  or denial-of-service via resource exhaustion against shared infrastructure.
- Vulnerabilities in dependencies that have not yet been fixed upstream (please report
  to the dependency's maintainers; we'll pick up patched releases promptly).

## Hall of fame

We're grateful to the researchers and contributors who report issues responsibly. Once
the project receives its first reports, this section will list reporters who follow the
disclosure process and consent to public credit.

- *(no reports yet — your name could go here!)*
