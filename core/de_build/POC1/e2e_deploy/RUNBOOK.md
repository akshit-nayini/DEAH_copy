# DE Hub Agent — End-to-End Deployment Runbook
## From Zero to Running Pipeline in BigQuery + Cloud Composer

---

## Prerequisites checklist

Before starting, confirm you have:

- [ ] GCP project with billing enabled
- [ ] BigQuery API enabled (`gcloud services enable bigquery.googleapis.com`)
- [ ] Cloud Composer API enabled (`gcloud services enable composer.googleapis.com`)
- [ ] `gcloud` CLI installed and authenticated (`gcloud auth login`)
- [ ] Python 3.11+ installed locally
- [ ] The POC1 agent code (from the repo)

---

## Overview: What we're building

```
┌─────────────────────────────────────────────────────────────┐
│                    SOURCE SYSTEMS                           │
│  source_crm    source_catalog  source_orders  source_events │
│  (customers)   (products)      (order_lines)  (events)      │
└──────┬──────────────┬──────────────┬──────────────┬─────────┘
       │              │              │              │
       ▼              ▼              ▼              ▼
┌─────────────────────────────────────────────────────────────┐
│              CLOUD COMPOSER (AIRFLOW)                        │
│                                                             │
│  ┌─────────┐  ┌──────────┐  ┌──────────┐  ┌─────────────┐ │
│  │ Staging  │→ │Dimensions│→ │  Facts   │→ │ Aggregates  │ │
│  │stg_events│  │dim_cust  │  │fct_orders│  │daily_sales  │ │
│  └─────────┘  │dim_prod  │  └──────────┘  └─────────────┘ │
│               │dim_ship  │                                  │
│               └──────────┘        ↓                         │
│                              ┌──────────┐                   │
│                              │ DQ Checks│                   │
│                              └──────────┘                   │
└─────────────────────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────────┐
│              BigQuery: de_hub_analytics                      │
│                                                             │
│  dim_customer (SCD-2)    │  fct_orders (incremental)        │
│  dim_product (SCD-1)     │  fct_daily_sales_summary (agg)   │
│  dim_shipping_region     │  stg_order_events (incremental)  │
└─────────────────────────────────────────────────────────────┘
```

---

## Phase 1: Source data setup (10 minutes)

### Step 1.1: Set your project

```bash
export PROJECT_ID="your-gcp-project-id"
export REGION="us-central1"

gcloud config set project ${PROJECT_ID}
```

### Step 1.2: Run the source data setup script

```bash
cd e2e_deploy/scripts
chmod +x setup_source_data.sh
./setup_source_data.sh ${PROJECT_ID} ${REGION}
```

This creates:
- 5 source datasets (`source_crm`, `source_catalog`, `source_orders`, `source_events`, `source_reference`)
- 2 target datasets (`de_hub_staging`, `de_hub_analytics`)
- 860 rows of synthetic sample data across 5 source tables

### Step 1.3: Verify in BigQuery Console

Open: `https://console.cloud.google.com/bigquery?project=${PROJECT_ID}`

Check that you see the source datasets in the left panel with data:
- `source_crm.customers` → 100 rows
- `source_catalog.products` → 50 rows
- `source_orders.order_lines` → 500 rows
- `source_events.order_status_changes` → 200 rows
- `source_reference.shipping_regions` → 10 rows

---

## Phase 2: Run the agent & execute pipeline (5 minutes)

### Step 2.1: Run the full pipeline

```bash
cd e2e_deploy/scripts
chmod +x run_pipeline.sh
./run_pipeline.sh ${PROJECT_ID} de_hub_analytics source
```

This does 4 things in sequence:
1. Runs the agent to generate DDL + DML SQL
2. Replaces `${PROJECT_ID}` and `${DATASET}` placeholders with your real values
3. Executes DDL — creates 6 target tables in `de_hub_analytics`
4. Executes DML — runs all transformations (SCD-2, SCD-1, incremental, full refresh)

### Step 2.2: Verify the results

In BigQuery Console, run these queries:

```sql
-- Check dim_customer (SCD-2: should have _is_current, _effective_from, _effective_to)
SELECT customer_id, first_name, customer_segment, _is_current, _effective_from, _effective_to
FROM `de_hub_analytics.dim_customer`
WHERE _is_current = TRUE
LIMIT 10;

-- Check dim_product (SCD-1: should have _loaded_at)
SELECT product_id, product_name, category, unit_price, _loaded_at
FROM `de_hub_analytics.dim_product`
LIMIT 10;

-- Check fct_orders (incremental: should have loaded_at and _loaded_at)
SELECT order_id, customer_id, product_id, order_date, total_amount, order_status
FROM `de_hub_analytics.fct_orders`
LIMIT 10;

-- Check fct_daily_sales_summary (aggregated from fct_orders)
SELECT summary_date, product_id, region, total_orders, gross_revenue, net_revenue
FROM `de_hub_analytics.fct_daily_sales_summary`
ORDER BY summary_date DESC
LIMIT 10;

-- Check referential integrity (should return 0)
SELECT COUNT(*) AS orphan_orders
FROM `de_hub_analytics.fct_orders` o
LEFT JOIN `de_hub_analytics.dim_customer` c
  ON o.customer_id = c.customer_id AND c._is_current = TRUE
WHERE c.customer_id IS NULL;
```

### Expected row counts:

| Table | Expected Rows | Notes |
|-------|--------------|-------|
| dim_customer | ~100 | 100 source customers, all current (_is_current=TRUE) |
| dim_product | ~50 | 50 products, SCD-1 (no history) |
| dim_shipping_region | 10 | Full refresh from reference |
| fct_orders | ~500 | 500 order lines, incremental append |
| stg_order_events | ~200 | 200 events, incremental append |
| fct_daily_sales_summary | ~365 | Daily aggregations from fct_orders |

---

## Phase 3: Deploy to Cloud Composer (15 minutes)

### Step 3.1: Verify Cloud Composer environment exists

```bash
gcloud composer environments list --locations=${REGION} --project=${PROJECT_ID}
```

If you don't have one yet, create it (takes ~25 minutes):

```bash
gcloud composer environments create de-hub-composer \
  --project=${PROJECT_ID} \
  --location=${REGION} \
  --image-version=composer-2.9.7-airflow-2.9.3 \
  --environment-size=small
```

### Step 3.2: Deploy the DAG

```bash
cd e2e_deploy/scripts
chmod +x deploy_to_composer.sh
./deploy_to_composer.sh ${PROJECT_ID} de-hub-composer ${REGION} de_hub_analytics
```

This:
1. Reads the Composer DAGs bucket path
2. Sets Airflow variables (`gcp_project_id`, `de_hub_target_dataset`)
3. Generates and uploads SQL files to the bucket
4. Uploads the DAG file

### Step 3.3: Verify in Airflow UI

Open the Airflow web UI (URL shown in the deploy script output, or find it in GCP Console → Cloud Composer → your environment → Airflow webserver).

You should see: `de_hub_ecommerce_pipeline` DAG

The DAG graph shows:
```
pipeline_start
  → load_stg_order_events
    → staging_complete
      → [load_dim_shipping_region, load_dim_product, load_dim_customer] (parallel)
        → dimensions_complete
          → load_fct_orders
            → facts_complete
              → load_fct_daily_sales_summary
                → [6 DQ checks] (parallel)
                  → pipeline_end
```

### Step 3.4: Trigger a manual run

Either click "Trigger DAG" in the Airflow UI, or:

```bash
gcloud composer environments run de-hub-composer \
  --project=${PROJECT_ID} \
  --location=${REGION} \
  dags trigger -- de_hub_ecommerce_pipeline
```

### Step 3.5: Monitor the run

In the Airflow UI:
1. Click on `de_hub_ecommerce_pipeline`
2. Click on the latest DAG run
3. Watch tasks turn green (success) one by one
4. If any task fails, click it → View Log to see the BigQuery error

---

## Phase 4: Test SCD-2 change detection (5 minutes)

This is the most impressive part of the demo — showing that the SCD-2 pattern actually works.

### Step 4.1: Update a customer in the source

```sql
-- Simulate a customer changing their segment from 'basic' to 'premium'
UPDATE `source_crm.customers`
SET customer_segment = 'premium',
    updated_at = CURRENT_TIMESTAMP()
WHERE cust_id = '3';

-- Simulate an address change
UPDATE `source_crm.customers`
SET city = 'San Francisco',
    state = 'CA',
    updated_at = CURRENT_TIMESTAMP()
WHERE cust_id = '7';
```

### Step 4.2: Re-run the pipeline

Trigger the DAG again (or run the DML manually):

```bash
gcloud composer environments run de-hub-composer \
  --project=${PROJECT_ID} \
  --location=${REGION} \
  dags trigger -- de_hub_ecommerce_pipeline
```

### Step 4.3: Verify SCD-2 history

```sql
-- Customer 3 should now have 2 rows: one closed, one current
SELECT
  customer_id,
  customer_segment,
  _is_current,
  _effective_from,
  _effective_to,
  _loaded_at
FROM `de_hub_analytics.dim_customer`
WHERE customer_id = 3
ORDER BY _effective_from;
```

Expected result:
```
customer_id | customer_segment | _is_current | _effective_from | _effective_to
3           | basic            | FALSE       | 2026-04-03      | 2026-04-02
3           | premium          | TRUE        | 2026-04-03      | 9999-12-31
```

This proves the SCD-2 MERGE correctly:
- Closed the old record (set `_is_current=FALSE`, `_effective_to=yesterday`)
- Inserted a new record with the updated segment (set `_is_current=TRUE`)

---

## Phase 5: Test incremental append (5 minutes)

### Step 5.1: Insert new orders in source

```sql
-- Add 5 new order lines with today's timestamp
INSERT INTO `source_orders.order_lines`
VALUES
  ('9001', 1, 5, 10, CURRENT_DATE(), 2, 99.99, NULL, 199.98, 'pending', NULL, CURRENT_TIMESTAMP()),
  ('9001', 2, 5, 20, CURRENT_DATE(), 1, 49.99, 5.00, 44.99, 'pending', NULL, CURRENT_TIMESTAMP()),
  ('9002', 1, 12, 30, CURRENT_DATE(), 3, 29.99, NULL, 89.97, 'confirmed', NULL, CURRENT_TIMESTAMP()),
  ('9003', 1, 88, 5, CURRENT_DATE(), 1, 499.99, 50.00, 449.99, 'shipped', CURRENT_DATE(), CURRENT_TIMESTAMP()),
  ('9003', 2, 88, 15, CURRENT_DATE(), 4, 19.99, NULL, 79.96, 'shipped', CURRENT_DATE(), CURRENT_TIMESTAMP());
```

### Step 5.2: Re-run and verify

Trigger the DAG, then check:

```sql
-- Should see 505 rows now (500 original + 5 new)
SELECT COUNT(*) FROM `de_hub_analytics.fct_orders`;

-- Verify the new orders landed
SELECT order_id, order_line_id, customer_id, total_amount, order_status
FROM `de_hub_analytics.fct_orders`
WHERE order_id IN (9001, 9002, 9003)
ORDER BY order_id, order_line_id;
```

The incremental append only loaded the 5 new rows (not re-processing all 500).

---

## What we demonstrated

| Capability | Status | Proof |
|-----------|--------|-------|
| DDL Generation (BigQuery-native) | ✅ Working | 6 tables created with partition, cluster, PII tags |
| SCD Type-2 MERGE | ✅ Working | Customer history tracked on re-run |
| SCD Type-1 MERGE | ✅ Working | Product overwrite with hash diff |
| Incremental Append | ✅ Working | Only new orders loaded on re-run |
| Full Refresh | ✅ Working | Shipping regions + daily summary rebuilt |
| Self-Review (correctness) | ✅ Working | Detects missing tables/columns |
| Self-Review (security) | ✅ Working | Flags unmasked PII columns |
| Cloud Composer DAG | ✅ Working | Orchestrated pipeline with DQ checks |
| Data Quality Checks | ✅ Working | FK integrity, null PKs, row reconciliation |

---

## Cleanup (optional)

To remove all resources created by this demo:

```bash
# Delete target datasets
bq rm -r -f ${PROJECT_ID}:de_hub_analytics
bq rm -r -f ${PROJECT_ID}:de_hub_staging

# Delete source datasets
for DS in source_crm source_catalog source_orders source_events source_reference; do
  bq rm -r -f ${PROJECT_ID}:${DS}
done

# Delete Composer environment (if created for demo)
gcloud composer environments delete de-hub-composer \
  --project=${PROJECT_ID} --location=${REGION} --quiet
```
