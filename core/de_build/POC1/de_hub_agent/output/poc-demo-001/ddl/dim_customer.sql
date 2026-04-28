-- =============================================================================
-- Table: dim_customer
-- Description: Customer dimension table with SCD Type-2 tracking for address and segment changes
-- Layer: dim
-- Refresh Strategy: scd_type_2
-- Source: source_crm.customers
-- Generated: 2026-04-03 20:14:31 UTC
-- Generator: DE_CodeGen_Optimizer_Agent v1.0
-- =============================================================================

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.${DATASET}.dim_customer`
(
  customer_id                    INT64 NOT NULL,                  OPTIONS(description='Unique customer identifier from source system')
  first_name                     STRING NOT NULL,                 OPTIONS(description='Customer first name')  -- PII: requires policy tag
  last_name                      STRING NOT NULL,                 OPTIONS(description='Customer last name')  -- PII: requires policy tag
  email                          STRING NOT NULL,                 OPTIONS(description='Customer email address')  -- PII: requires policy tag
  phone                          STRING,                          OPTIONS(description='Customer phone number')  -- PII: requires policy tag
  address_line1                  STRING,                          OPTIONS(description='Street address line 1')  -- PII: requires policy tag
  city                           STRING,                          OPTIONS(description='City name')
  state                          STRING,                          OPTIONS(description='State or province code')
  country                        STRING,                          OPTIONS(description='ISO 3166-1 country code')
  customer_segment               STRING,                          OPTIONS(description='Business segment: premium, standard, basic')
  created_date                   DATE NOT NULL,                   OPTIONS(description='Account creation date')
  updated_at                     TIMESTAMP NOT NULL,              OPTIONS(description='Last modification timestamp from source')
  _surrogate_key                 INT64 NOT NULL,                  OPTIONS(description='Surrogate key generated via FARM_FINGERPRINT')
  _effective_from                DATE NOT NULL,                   OPTIONS(description='SCD-2: record effective start date')
  _effective_to                  DATE NOT NULL,                   OPTIONS(description='SCD-2: record effective end date (9999-12-31 for current)')
  _is_current                    BOOL NOT NULL,                   OPTIONS(description='SCD-2: true if this is the current active record')
  _row_hash                      BYTES NOT NULL,                  OPTIONS(description='SHA256 hash of business columns for change detection')
  _loaded_at                     TIMESTAMP NOT NULL               OPTIONS(description='ETL load timestamp')
)
PARTITION BY DATE_TRUNC(created_date, MONTH)
CLUSTER BY customer_segment, country
OPTIONS(
  description='Customer dimension table with SCD Type-2 tracking for address and segment changes',
  labels=["layer=dim", "refresh=scd_type_2", "contains_pii=true"]
);
