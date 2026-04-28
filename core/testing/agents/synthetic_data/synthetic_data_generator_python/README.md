# Synthetic Data Generator — GitHub Actions Version

Auto-generates BigQuery-ready synthetic SQL data whenever a source file
is pushed/merged to `main`. No manual steps — fully automated via GitHub Actions.

---

## How It Works

```
Designer drops CSV/JSON into source_tables/
          │
          ▼
Merge to main (PR or direct push)
          │
          ▼
GitHub Actions triggers automatically
          │
          ▼
Detects which files changed in source_tables/
          │
          ▼
For each changed file:
  ├── Load source rows (up to 1,000 for analysis)
  ├── Analyze columns (types, ENUMs, ID patterns, ranges, nullability)
  ├── Compute date range (today minus date_window_days → today)
  ├── Generate N synthetic rows
  └── Write BigQuery INSERT SQL → output/<table_name>.sql
          │
          ▼
GitHub Actions auto-commits output/ back to main
```

---

## Folder Structure

```
synthetic_data_generator_python/
├── config.json             ← Edit this to configure the generator
├── source_tables/          ← Designers drop files here
│   └── .gitkeep
├── output/                 ← Auto-generated SQL lands here (committed by bot)
│   └── .gitkeep
└── src/
    ├── main.py             ← Orchestrator (called by GitHub Actions)
    ├── scanner.py          ← Detects and resolves changed files
    ├── data_loader.py      ← Loads CSV / JSON source files
    ├── column_analyzer.py  ← Profiles columns (types, ENUMs, ranges…)
    ├── data_generator.py   ← Generates synthetic rows
    └── sql_writer.py       ← Writes BigQuery INSERT SQL
```

The GitHub Actions workflow lives at the **repo root**:
```
.github/workflows/synthetic_data_generator.yml
```

---

## Configuration (`config.json`)

```json
{
    "bq_project"       : "your-gcp-project",
    "bq_dataset"       : "your_dataset",
    "num_records"      : 500,
    "date_window_days" : 15,
    "output_format"    : "bigquery_insert"
}
```

| Field | Description | Editable |
|---|---|---|
| `bq_project` | GCP project ID used in INSERT statement | ✅ |
| `bq_dataset` | BigQuery dataset name used in INSERT statement | ✅ |
| `num_records` | Number of synthetic rows to generate per table | ✅ |
| `date_window_days` | `from_date = today - N days`, `to_date = today` | ✅ |
| `output_format` | Output format (currently only `bigquery_insert`) | ✅ |

---

## Output SQL Format

Generated file: `output/<source_filename>.sql`

```sql
-- ============================================================
-- Synthetic Data : orders
-- Generated at  : 2024-04-15 08:30:00 UTC
-- Records       : 500
-- Date range    : 2024-03-31 → 2024-04-15
-- Source file   : orders  (source_tables/)
-- Target table  : `your-gcp-project.your_dataset.orders`
-- Trigger       : GitHub Actions (push to main)
-- ============================================================

INSERT INTO `your-gcp-project.your_dataset.orders`
  (`order_id`, `customer_id`, `status`, `total_amount`, ...)
VALUES
  ('ORD-10482', 'CUST-3291', 'completed', 149.99, ...),
  ('ORD-10835', 'CUST-7104', 'shipped',   89.50,  ...),
  ...
;
```

- Table name = source filename (without extension)
- Project and dataset come from `config.json`
- One INSERT statement with all rows as VALUES
- `DATE('...')` and `DATETIME('...')` BQ literals
- Backtick-quoted column and table names

---

## Triggering the Generator

### Standard flow (recommended)
1. Designer creates a branch
2. Drops their CSV/JSON into `source_tables/`
3. Opens a PR → merges to `main`
4. GitHub Actions triggers automatically
5. SQL appears in `output/` within ~1 minute

### Direct push to main
1. Drop CSV/JSON into `source_tables/`
2. Push directly to `main`
3. Same result — Actions triggers immediately

### Multiple files at once
Push multiple files in one commit — all are processed in parallel.

---

## First-Time Setup in Your Repo

No secrets or special settings required — the workflow uses the built-in
`GITHUB_TOKEN` which GitHub provides automatically.

The only thing to verify:

1. Go to your repo → **Settings → Actions → General**
2. Under **Workflow permissions** → select **Read and write permissions**
3. Click **Save**

This allows the bot to auto-commit the generated SQL back to `main`.

---

## Multi-File Support

When multiple source files are pushed in one merge, all are processed:

```
source_tables/orders.csv      →  output/orders.sql
source_tables/customers.csv   →  output/customers.sql
source_tables/products.csv    →  output/products.sql
```

Each gets its own SQL file. All are committed together in one bot commit.

---

## Re-Processing / Overwrite

If a source file is updated and pushed again:
- The workflow detects it as a changed file
- Generates fresh SQL with new random data
- **Overwrites** the existing SQL in `output/`

---

## Column Intelligence

| Pattern | Detection | Generation |
|---|---|---|
| **ENUM** (status, currency…) | ≤30 distinct values | Random choice from observed values |
| **Prefixed ID** (ORD-XXXXX) | PREFIX-DIGITS pattern | Fresh IDs — same prefix, same digit width |
| **UUID** | UUID format | Valid UUID4 |
| **Integer** | All values parse as int | Random int in min→max |
| **Float** | All values parse as float | Random float in min→max, 2dp |
| **Date** | Matches date format | Random date in `from_date → to_date` |
| **Datetime** | Matches datetime format | Random datetime in range |
| **Boolean** | true/false/yes/no/1/0 | TRUE or FALSE |
| **String** | Everything else | Random plausible words in min→max length |
| **Nullable** | Has nulls in source | Reproduced at observed null rate |
