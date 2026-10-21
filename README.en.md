# Local Reconcile

A local Windows reconciliation and settlement workbench for Chinese private businesses. Version **0.4.1**. MIT-licensed application code; dependencies retain their own licenses.

[中文](README.md)

## Business workflows

- Import XLSX and UTF-8 CSV bank statements, cash journals, receivables and payables with confirmed column mappings.
- Suggest one-to-one, one-to-many and many-to-many equal-sum matches. Automatic combinations use up to five records per side; manual combinations allow up to 100 per side. Matching requires the same own CNY account and payment direction.
- Retain candidate ambiguity and evidence. Conflicting references never silently fall back to a weaker automatic rule. Large pools and search budgets produce explicit incomplete-search ranges. Budgets and cancellation checks also cover candidate-pool construction.
- Explain settlement differences without treating them as equal matches.
- Preserve month-end outstanding and open-item snapshots while continuing in later periods.
- Partially allocate receipts/payments to open invoices, with available-cash and invoice-balance checks.
- Identify transfers between registered own CNY bank accounts, with separately evidenced fees.
- Link actual opposite-direction bank refunds, reversals or returned cheques to original cash records. Partial refunds can reopen the original allocated invoice balance or reduce unused advances.
- Register customer advances and supplier prepayments, reserve their cash, and allocate them in parts to later invoices for the same party and appropriate direction.

Refunds preserve original bank data and historical closing snapshots. They do not void invoices or post credit notes/accounting entries. Undo checks subsequent allocations and cannot overallocate invoices. Mixed-sign netting, FX conversion and automatic posting are outside the scope.

## Period-end reports

- Record bank-statement and journal closing balances explicitly for each own CNY account and period, retaining supporting evidence. Manually review the four timing-difference categories before adjustment; pending items never silently become adjustments.
- Adjust the bank balance for journal-only receipts/payments, and the journal balance for bank-only receipts/payments. A zero difference with unreviewed items is still marked for review. Missing closing balances are never inferred or carried to a new month.
- Analyze net outstanding receivables/payables by party in 0–30,31–60,61–90,and over90-day invoice-age buckets. Overdue days use due dates; missing due dates remain separate. Partial allocations and refunds affect the remaining balance.
- Filter by party, role or overdue status. Month-end snapshots retain both reports and the account membership present at closing; later events do not rewrite the old reports. Excel export includes balance adjustment, source details, aging summaries and an open-item follow-up list.

Choose the synthetic period-end example from the example picker. Workspaces containing new reporting events require 0.4.0 or later.

## Run

Unpack a Windows portable build and run `LocalReconcile.exe`; no separate Python installation is needed. The repository also includes the source and a reproducible Windows build script.

For source execution, use Python 3.12 on Windows x64, create a virtual environment outside the source directory, install `requirements.lock`, set `PYTHONPATH` to the absolute `src` directory, then run `python -B -m local_reconcile`. See the Chinese README for full commands.

Open the business workbench and load the synthetic example to explore all workflows without real company data. Each proposed relationship requires human review.

## Storage and reports

`.lrwork` workspaces retain typed source snapshots, checksums and a replayable event history. Earlier workspaces remain readable; files containing new settlement events require 0.3.0 or later. Existing `.lrproj` one-to-one projects can be imported without modifying the originals.

Excel reports include confirmed matches, individual components, candidates, search limitations, difference evidence, outstanding items, historical balances, allocations, refunds, advances, internal transfers, original rows and events. All calculations use integer minor units. Original text is exported as text rather than executable spreadsheet formulas.

Core workflows run locally, without an account, API key, telemetry or financial-data upload. Workspace files are unencrypted financial snapshots. Never commit actual company data to a public repository.

## Development and verification

Install pinned dependencies from `requirements-dev.lock` in an external environment. Run `scripts/verify.ps1` for source verification and `scripts/build_windows.ps1` for packaging; use output paths outside the source tree. The build collects third-party notices and corresponding Qt source materials and checks the frozen executable.

Synthetic tests and code review do not replace real-company validation. Real company trials and clean Windows-machine acceptance are not yet complete. Accounting decisions require review against actual business records.
