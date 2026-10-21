---
name: softory-secure-coding
description: Secure-coding rules for every softory engineer and the procedure Toby follows for threat models and security reviews, mapped to the OWASP Top 10:2025. Use when touching auth, user data, secrets, input handling, file or network access, or dependencies, and when performing a security review.
---

# Secure coding

## Rules for everyone who writes code

**Input and output**
- Validate all external input at the boundary: type, length, range, and format. Use allow-lists over deny-lists.
- Use parameterized queries or the ORM's binding. Never build SQL, shell commands, file paths, or HTML by string concatenation with input.
- Encode output for its context (HTML, attribute, URL, JS). Rely on the framework's auto-escaping and don't bypass it.
- Treat file names and paths from input as hostile. Resolve them, then check they stay inside the allowed directory.

**Access**
- Check authorization **server-side, on every request**, for every object (no ID-guessing access). Deny by default.
- Never trust client-side checks, hidden fields, or IDs in URLs for access decisions.

**Secrets and data**
- No secrets in code, config committed to git, logs, test fixtures, error messages, or coordination records. Read them from the environment or a secret store.
- Collect and keep only the data the feature needs. Know which fields are personal or sensitive, and tag the task `data`.
- Never log tokens, passwords, full personal records, or request bodies that may contain them.

**Crypto and auth**
- Use the platform's vetted libraries. Never write your own crypto, token format, or password hashing. Use argon2, scrypt, or bcrypt for passwords.
- Use secure, HttpOnly, SameSite cookies for sessions, rotate the session on login, and rate-limit authentication endpoints.

**Dependencies**
- Every new or upgraded dependency is tagged `deps` and justified in the task: why it's needed, its maintenance status, its license, and its transitive weight.
- Pin versions through a lockfile. Prefer well-maintained, widely used packages. Never run install scripts from unknown sources.

**Errors**
- Fail closed. A failed authorization or validation check denies.
- Error responses don't leak stack traces, queries, or internal IDs.

Tag the task `security`, `auth`, `data`, or `deps` whenever one of these areas is touched. Toby is then a required reviewer.

## Toby: threat model (per epic, before go/no-go)

Write `docs/security/EPIC-n-threat-model.md` that answers four questions:

1. **What are we working on?** Components, data stores, and external actors, with the trust boundaries marked.
2. **What can go wrong?** STRIDE per boundary crossing: spoofing, tampering, repudiation, information disclosure, denial of service, and elevation of privilege.
3. **What are we going to do about it?** Each threat gets a mitigation, as an acceptance criterion on a story or a `security`-tagged task, or an **accepted risk** that the owner records as a decision.
4. **Did we do a good enough job?** Revisit when the epic closes, and note what changed.

## Toby: security review procedure

1. Read the task, its tags, and the threat model's mitigations for this area.
2. Read the diff and trace each input from where it enters to where it is used.
3. Walk the OWASP Top 10:2025 categories that apply: A01 Broken Access Control, A02 Security Misconfiguration, A03 Software Supply Chain Failures, A04 Cryptographic Failures, A05 Injection, A06 Insecure Design, A07 Authentication Failures, A08 Software or Data Integrity Failures, A09 Security Logging and Alerting Failures, and A10 Mishandling of Exceptional Conditions.
4. Run the project's static analysis and dependency audit if available, for example `semgrep`, `npm audit`, or `pip-audit`. Attach a short result as evidence.
5. Verify each suspected finding before reporting it: is it reachable, is it exploitable, and what's the impact. Drop false positives.
6. Record the review. Each finding has a severity (critical, high, medium, or low), its evidence, and a concrete fix. `--blocked-claims` states what the sign-off doesn't cover.
7. Add each finding to `docs/security/findings.md` with its owner and status.

## Severity and release

| Severity | Release impact |
| --- | --- |
| Critical | Blocks. Fix now. Toby may fix it under the flex rule, and the lane owner and Quinn review the fix. |
| High | Blocks unless the owner records an accepted risk |
| Medium | Fix within the epic |
| Low | Backlog task |

Sources: [OWASP Top 10:2025](https://owasp.org/Top10/2025/). [OWASP ASVS](https://owasp.org/www-project-application-security-verification-standard/). [OWASP Cheat Sheet Series](https://cheatsheetseries.owasp.org/). [NIST SP 800-218 SSDF](https://csrc.nist.gov/pubs/sp/800/218/final). [Threat Modeling Manifesto](https://www.threatmodelingmanifesto.org/).
