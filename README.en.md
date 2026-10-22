# Local Reconcile

A local Windows reconciliation and settlement workbench for Chinese private businesses. Version **0.7.0**. MIT-licensed application code; dependencies retain their own licenses.

[中文](README.md)

## Evidence, contract milestones and corrections

- Group structured business documents by exact party, business ID and receivable/payable direction. Explicit required-document rules flag missing proof, signed-invoice/net-payment limits and unlinked cash. Bank proof is separate from document amounts; confirmation requires a clean evidenced review.
- Register contract milestones with positive planned amounts, verified triggers and explicit day offsets. Missing acceptance/invoice evidence leaves the due date unknown. Track actual settlement/refunds, outstanding amounts, overdue days and early/unverified-condition payments.
- Queue correction operations and preview their effects on balances, aging, reconciliation and milestones without modifying the workspace. Dependencies remain explicit. Apply resimulates the entire plan atomically, rejects changed workspaces/plans/reasons and retains audit evidence.

Choose the synthetic evidence/contract/correction example in the business workbench. Import `business_evidence` with date, amount, party, unique document ID, business ID, kind and receivable/payable direction. Contract/payment/refund documents require positive amounts; signed nonzero invoices support credits; other proof can be zero. No OCR, legal-term interpretation or automatic posting. Evidence and milestone bank links are independent proof layers with separate capacity limits; they do not consume invoice allocations. Due/overdue status is measured at the selected month end. Late evidence affects current reports while stored month ends remain immutable. New events require 0.7.0 or later; older workspaces remain readable.

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

## Credit adjustments, duplicates and partner statements

- Apply evidenced sales/purchase credit notes, returns and allowances to invoices for the same party and direction. Positive or negative input becomes an absolute available credit limit; raw signed cells remain intact. Credit reductions are separate from net cash settlements. A settled invoice needs an actual linked refund before crediting the reopened balance. Undo cannot over-settle an invoice.
- Review suspicious bank/journal records across different import batches. Account, party, amount and reference (or date when a reference is missing) form warnings; pending records are blocked from further cash use or confirmation. Evidence can mark the whole group as distinct transactions, or exclude a genuine duplicate while retaining its source. New group membership requires a new review.
- Import a single customer's or supplier's month-end statement, using our receivable/payable perspective and one nonnegative outstanding amount per invoice. Register the current month-end cutoff and evidence. Compare exact party/reference balances after refunds and credits; distinguish missing invoices from zero balances. Only equal rows can be confirmed. Explanations retain discrepancies; changed balances invalidate previous decisions.
- Month-end snapshots and Excel exports retain the comparison and duplicate evidence. Re-importing an unchanged statement in a later month creates a separate monthly snapshot. New events require version 0.5.0 or later. Choose the new synthetic commercial example to explore the workflows.

[Download the Windows portable release](https://github.com/edcee314159/local-reconcile/releases/latest).

## Net settlements and month-end recognition checks

- Import original gross orders, signed settlement components and bank records. Sales/additions are positive; refunds, commissions, freight and deductions are negative. Each component needs a unique line ID and settlement ID; sales/refunds need exact original order references and party names.
- Reconstruct net cash from explicit evidence. Missing orders, cumulative over-settlement or over-refund prevent confirmation. Confirm only an exact signed bank total from one own CNY account (a zero-net batch without cash movement may use no bank rows with evidence); bank records cannot be confirmed in two settlement groups. This proof does not post revenue/expenses or allocate invoice balances. Changed sources require another review, even after exclusion/restore.
- Separately import positive receipt/acceptance/service business amounts and signed actual posting entries with unique voucher-line IDs. Confirm a consistent amount basis and an evidenced once/monthly/daily recognition rule manually. Integer schedules conserve the original amount, including leap days and rounding remainders.
- Compare expected and actual amounts for the current month and separately for earlier periods. Missing rules remain unknown; unmatched postings stay visible; future postings do not count in the current month. Flag invoice/payment timing differences and negative cumulative postings. Explanations never clear the underlying discrepancy.
- Current reports may include late evidence with prior business dates; immutable month-end snapshots retain what was known then. Six Excel sheets expose summaries, components, order checks, bank proof, recognition differences and source evidence. Choose the new synthetic advanced example. New events/extra source mappings require version 0.6.0 or later; earlier workspaces remain readable.

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
