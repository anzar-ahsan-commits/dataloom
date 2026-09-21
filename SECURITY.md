# Security policy

DataLoom is an alpha developer tool. Security fixes target the latest development
revision on `main`; no long-term support or response-time commitment is offered.

## Reporting a vulnerability

Please do not disclose vulnerabilities, credentials, production records, or
confidential schemas in public issues. Use GitHub's **Report a vulnerability**
button under this repository's Security tab when available. If private reporting
is unavailable, email the maintainer at `Anzar.ahsan.us@gmail.com` with a minimal
fictional reproduction, affected revision, impact, and environment details.

## Trust boundaries

- DDL is parsed, not executed. Supported constraints are documented in
  [scope](docs/scope.md); validation does not model every database behavior.
- The MCP server uses local stdio. Workspace path checks are not a multi-user
  isolation mechanism or a substitute for operating-system permissions.
- Domain packs execute trusted Python code. Install packs you trust.
- Profiling is optional and can store observed source values in genome artifacts.
  Review those artifacts before sharing or committing them.
- Optional provider calls send selected schema metadata and user prompts. Those
  inputs can themselves contain confidential information.
- Database export inserts into existing tables. Use a dedicated test database.
- Synthetic generation is not anonymization, differential privacy, or a
  compliance certification. Masking and subsetting are not implemented.

Keep credentials in environment variables or an appropriate local credential
store. Never put real secrets or production samples in issue attachments.
