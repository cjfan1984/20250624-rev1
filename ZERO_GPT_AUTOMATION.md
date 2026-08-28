# Zero-GPT automation contract

This repository now owns repetitive SKU work. Scheduled execution is ordinary Python in GitHub Actions; it must not call ChatGPT, an LLM API, browser agents, or web search.

## Canonical workflow

`.github/workflows/sku-zero-gpt.yml` runs once per day at 23:30 Asia/Shanghai and can also be started manually.

1. Compile and run regression tests.
2. Hash the Ozon/WB source sheets.
3. If the source hash is unchanged, stop candidate selection.
4. On a genuinely changed source, select no more than five direct Ozon product candidates, deduplicate against the master/daily layers, and write only evidence-backed fields to `每日新品_决策卡数据层`.
5. Validate master/snapshot coverage, duplicate IDs, dates, and shifted-column signatures.
6. Compute the stable dataset hash before encryption.
7. If the dataset hash is unchanged, do not encrypt, fragment, commit, or publish.
8. If changed, reuse the existing V4 data builder and hybrid encryption, run the publication contract, and commit only encrypted fragments plus non-sensitive state hashes.

The old V4 sync and fragment workflows are manual-only. The auth publisher runs only when its shell/envelope sources change, so encrypted data/state commits cannot trigger a competing publication. These workflows are retained for rollback and forensic comparison, not normal scheduling.

## Safety rules

- Unknown prices, weights, fees, margins, orders, and URLs remain blank or explicitly pending; zero is never substituted.
- Model-estimated packaging never enters factual weight/dimension columns.
- Candidate creation is capped at five and one candidate per product family per run.
- High-risk categories are rejected by deterministic policy.
- Any master/snapshot field shift, duplicate identity, or invalid update date blocks publication.
- A source change may create a candidate; it never means that a product is profitable or ready to list.
- GPT is reserved for a human-triggered exception: ambiguous evidence, a rule change, or a failed test requiring code repair.

## Credentials and remaining adapters

`GOOGLE_SERVICE_ACCOUNT_JSON` is the only credential used by the current scheduled pipeline. It must have access to the authoritative spreadsheet. The first run only records the current Ozon/WB source fingerprint, preventing an old backlog from being auto-imported.

Direct Ozon/WB seller-account operations and three-mailbox ingestion stay disabled until official API/OAuth credentials are installed in the relevant repository. Missing credentials are a hard stop; they must not trigger a GPT/browser fallback.

## Maintenance

Before changing rules:

```bash
python -m pytest -q
```

Add or update a regression test for every defect. In particular, preserve tests for:

- shifted master columns;
- invalid snapshot dates;
- stable dataset hashes;
- unchanged-data encryption skip;
- deterministic candidate deduplication and family diversity;
- keeping estimated logistics values out of factual columns.
