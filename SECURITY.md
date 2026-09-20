# Security Policy

## Reporting a Vulnerability

Please report security issues privately by opening a draft security advisory or
contacting the maintainers directly. Do not include secrets, private documents,
or customer data in public issues.

## Secret Handling

Runtime credentials should be provided through environment variables or an
explicit configuration file copied from `config.json.example`. Mutable runtime
state is written to `DOCSIFTER_DATA_DIR` (default: `./data`), which is ignored
by git along with `.env` files, generated reports, logs, and SQLite databases.
Environment-provided secrets stay in memory and are not persisted when runtime
configuration is updated.

If a credential is committed accidentally, rotate it immediately and rewrite the
repository history before publishing the repository.

## Web UI Exposure

The web UI is intended for local or controlled-network use. Set
`DOCSIFTER_ADMIN_TOKEN` to protect the UI and management APIs with HTTP Basic or
Bearer authentication. DocSifter refuses to start with `DOCSIFTER_PUBLIC_URL`
unless an administrator token of at least 24 characters is configured.

For GitHub Webhook deployments, terminate HTTPS at a trusted reverse proxy and
expose only `/api/github/webhook` without administrator authentication. Keep all
other paths protected. The public Webhook endpoint verifies GitHub signatures;
management mutations additionally require a non-simple request header to prevent
cross-site form submissions. Filesystem access is limited to the startup
directory by default. Configure `DOCSIFTER_ALLOWED_ROOTS` explicitly when the Web
UI needs additional roots.
