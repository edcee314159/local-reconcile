# Local Reconcile

A local Chinese-language Windows workbench for comparing bank statements with a bank journal.

Import XLSX or UTF-8 CSV, confirm columns and amount direction, inspect explainable candidates and differences, review relations, save projects, and export a traceable eight-sheet Excel report. No account, API key, cloud upload, telemetry or automatic posting.

## Try it

This first publication is a **source alpha**; no downloadable Windows portable release is published yet. Install Python 3.12 x64 and follow the source startup commands in the Chinese README. Choose the synthetic demo, review mappings, check the confirmation box and run reconciliation. Select a candidate to inspect original source rows.

This is an **alpha** verified with synthetic cases. Real-company validation and clean-machine Windows acceptance remain outstanding. Scope: a single CNY account, one-to-one reconciliation, XLSX and UTF-8 CSV. One-to-many settlement, OCR and foreign exchange are outside this release.

Suggestions are not confirmations. Ambiguous records remain visible, manual decisions can be reversed, and no input file is overwritten. Project files contain financial snapshots and are not encrypted.

## Development

Python 3.12 x64, PySide6 Essentials, openpyxl and defusedxml. Install pinned dependencies with hashes from requirements-dev.lock in a dedicated environment. See the Chinese README for verification and packaging commands. Keep all generated test/build outputs outside the source directory.

Own application code: MIT. Dependencies retain their licenses; corresponding Qt/PySide source archives and rebuild information accompany the portable distribution.

Please report issues with synthetic or authorized redacted examples, never private bank records.
