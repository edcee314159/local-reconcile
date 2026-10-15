# Local Reconcile

A local Chinese-language Windows workbench for financial reconciliation and receivable/payable settlement, designed for privately owned businesses in China.

Import XLSX or UTF-8 CSV, confirm columns and amount direction, inspect traceable candidates, review relations, save workspaces, and export Excel reports. The business workbench provides:

- One-to-many and many-to-one reconciliation.
- Evidence-backed explanations of fees and other amount differences.
- Month-end snapshots and outstanding-item tracking across periods.
- Partial receivable/payable settlement with remaining-balance checks.
- Internal-transfer reconciliation across registered company CNY bank accounts.

Suggestions require human confirmation. Source records and review history remain traceable. Difference explanations do not turn unequal amounts into equal matches.

## Get started

Install Python 3.12 x64 and follow the source startup commands in the Chinese README. Open the business workbench from the sidebar, then load its synthetic demo to explore the five workflows. The original one-to-one workflow remains available.

Workspaces run locally without an account, API key, telemetry or automatic posting. Workspace files contain unencrypted source snapshots. Do not submit private financial records to the public repository.

## Scope and validation

CNY accounts, XLSX and UTF-8 CSV. Automatic combinations support up to five entries; manual combinations support up to 100. Search limits remain visible. Many-to-many netting, OCR and foreign exchange are outside the current scope. Real-company validation and clean-machine Windows acceptance remain outstanding.

## Development

Use Python 3.12 x64 and install pinned dependencies with hashes from requirements-dev.lock in a dedicated environment. See the Chinese README for verification and packaging commands. Keep generated outputs outside the source directory.

Application code: MIT. Dependencies retain their licenses; corresponding Qt/PySide source archives and rebuild information accompany portable builds.

Please report issues using synthetic or authorized redacted examples.
