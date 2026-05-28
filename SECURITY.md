# Security Policy

## Supported versions

This project is maintained on the `main` branch. Security fixes are applied to `main` only.

| Branch | Supported |
|--------|-----------|
| `main` | ✅ Yes |
| `develop` | ⚠️ Active development — fixes merged to main |
| Other branches | ❌ No |

## Reporting a vulnerability

This is a personal open-source project. If you discover a security issue please report it responsibly rather than opening a public issue.

**How to report:**
1. Email: use the contact details on the [GitHub profile](https://github.com/kere-sifon)
2. Or open a [private security advisory](../../security/advisories/new) on this repository

**What to include:**
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Any suggested fix (optional but appreciated)

**Response time:**
- Acknowledgement within 5 business days
- Assessment and fix timeline within 14 days for confirmed issues

## Security design

This project follows these security practices:

- **No long-lived credentials** — AWS access via GitHub OIDC role assumption only; no `AWS_ACCESS_KEY_ID` or `AWS_SECRET_ACCESS_KEY` stored anywhere
- **Secret scanning** — Gitleaks scans the full commit history on every push (pre-commit hook + CI)
- **SAST** — Bandit and CodeQL run on every push and weekly on schedule
- **Dependency scanning** — pip-audit on every push; Dependabot weekly PRs for pip and GitHub Actions
- **Action pinning** — all GitHub Actions pinned to full SHA commit hashes to prevent supply chain attacks
- **Least-privilege IAM** — IAM policy scoped to specific Bedrock model ARNs only; no wildcard service permissions
- **Environment-only secrets** — all credentials loaded from environment variables; zero hardcoded values in source

## Scope

**In scope:**
- Credential exposure or secret leakage
- Dependency vulnerabilities in `requirements.txt`
- GitHub Actions supply chain issues
- AWS IAM privilege escalation paths
- MongoDB Atlas connection string exposure

**Out of scope:**
- Web scraping rate limiting or terms of service questions
- Data accuracy of scraped store listings
- Third-party service availability (AWS Bedrock, MongoDB Atlas, DuckDuckGo)
