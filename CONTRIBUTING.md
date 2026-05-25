# Contributing to Enterprise MCP Server

## Welcome

Thanks for your interest in Enterprise MCP Server! This project thrives on community
contributions — whether you're fixing a typo, filing a bug report, proposing a new
feature, or shipping a substantial pull request, your help is appreciated. This document
explains how to get set up and what we expect from contributors.

## Ground rules

- **Be respectful.** All interactions are governed by our [Code of Conduct](CODE_OF_CONDUCT.md).
  Be kind, assume good faith, and disagree without being disagreeable.
- **Search existing issues and PRs first.** Someone may already be working on the same
  thing, or the question may have been answered. Avoid duplicates.
- **Keep PRs small and focused.** One logical change per PR. Large omnibus PRs are
  hard to review and often get stuck. If a change is big, open an issue first to discuss
  the approach.
- **Reach out early.** For non-trivial work, open an issue or discussion before writing
  code so we can align on direction.

## Dev environment setup

Enterprise MCP Server requires:

- **Python 3.12 or 3.13** (`requires-python = ">=3.12,<3.14"`)
- **[uv](https://docs.astral.sh/uv/)** for dependency management
- **Docker + Docker Compose** (for PostgreSQL, Redis, and the full local stack)
- **Node.js 20+** — only if you're working on the optional Claude Code CLI integration

Clone and bootstrap:

```bash
git clone https://github.com/nonagenticai/enterprise_mcp_server.git
cd enterprise_mcp_server
cp .env.example .env
# edit .env — see the "Setup and Installation" section of README.md for the variables
```

Install dependencies (the package lives in `src/`, built with hatchling):

```bash
uv sync
```

Bring up the backing services (PostgreSQL + Redis) for local work:

```bash
docker compose up -d postgres redis
```

For the full stack (gateway + server + Postgres + Redis), and for the Claude-integration
setup script, see the **Setup and Installation** section of [`README.md`](README.md).

## Running the test suite

Tests run with `pytest` from the repo root:

```bash
uv run pytest
```

Tests that touch the database expect a running PostgreSQL (start it with `docker compose
up -d postgres` as above). Make sure the suite is green before you push.

## Lint and formatting

| Language | Tool | Config |
|---|---|---|
| Python | `ruff check` and `ruff format` | `pyproject.toml` |
| Shell  | `shellcheck` (for `scripts/`, `init_db.sh`) | inline directives where needed |

```bash
uv run ruff check .
uv run ruff format --check .
```

There is no CI gate on this repository yet, so running these locally before opening a PR
is what keeps `main` clean — please don't skip it.

## Branch naming

Use a short prefix that describes the kind of change:

- `feat/` — new functionality (e.g. `feat/per-domain-rate-limits`)
- `fix/`  — bug fixes (e.g. `fix/token-refresh-race`)
- `docs/` — documentation only (e.g. `docs/clarify-gateway-routing`)
- `chore/` — refactors, dependency bumps, tooling (e.g. `chore/bump-ruff-0.6`)

## Commit messages

- **Imperative mood, present tense.** `Add foo`, not `Added foo` or `Adds foo`.
- **Subject line ≤72 characters.** No trailing period.
- **Body wrapped at ~72 chars** if more context is needed. Explain the *why*, not just
  the *what* — the diff already shows the what.
- **Reference issues** in the body: `Fixes #123`, `Refs #456`.

## Pull request conventions

1. Link the related issue if one exists (`Fixes #N`).
2. Describe what changed and why — give reviewers enough context to evaluate the change
   without reverse-engineering it from the diff.
3. Run the tests and lint locally before requesting review (there's no CI to catch a red
   build for you).
4. Request review from a maintainer once the PR is ready. Mark drafts as draft.
5. Be responsive to review feedback. Push fix-up commits and squash-merge at the end.

## DCO sign-off

Enterprise MCP Server uses the [Developer Certificate of Origin](https://developercertificate.org).
By signing your commits, you certify that you wrote (or have the right to submit) the
contribution under the project's open-source license.

Sign each commit with:

```bash
git commit -s -m "Add foo"
```

This appends a `Signed-off-by: Your Name <your@email>` trailer. Configure `git config
user.name` and `git config user.email` correctly first.

## Reporting bugs / requesting features

- **Bugs and feature requests:** open a [GitHub Issue](https://github.com/nonagenticai/enterprise_mcp_server/issues).
  Include reproduction steps, expected vs. actual behaviour, and version/commit for bugs.
- **Questions / discussion:** use GitHub Discussions rather than Issues.

## Security issues

**Do not file public issues for security vulnerabilities.** See [SECURITY.md](SECURITY.md)
for the disclosure process. We follow coordinated disclosure and will credit reporters
who follow it.

---

Thanks again for contributing to Enterprise MCP Server!
