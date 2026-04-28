# Self-Review Report
**Request ID:** poc-demo-001
**Generated:** 2026-04-03 20:14:31 UTC
**Tables reviewed:** 6

## CORRECTNESS Review
**Verdict:** PASS
**Summary:** Correctness review: 0 critical, 0 warning, 0 info findings

No findings. All checks passed.

**Stats:**
- tables_checked: 6
- ddl_files_found: 6
- dml_files_found: 6
- critical_count: 0
- warning_count: 0

## SECURITY Review
**Verdict:** CONDITIONAL_PASS
**Summary:** Security review: 0 critical, 5 warning findings

| Severity | Check | File | Description | Fix |
|----------|-------|------|-------------|-----|
| WARNING | PII_UNMASKED | merge_dim_customer.sql | PII column 'first_name' appears unmasked in DML for non-staging table 'dim_customer' | Apply masking: SHA256(CAST(first_name AS BYTES)) or use BigQuery column-level policy tags |
| WARNING | PII_UNMASKED | merge_dim_customer.sql | PII column 'last_name' appears unmasked in DML for non-staging table 'dim_customer' | Apply masking: SHA256(CAST(last_name AS BYTES)) or use BigQuery column-level policy tags |
| WARNING | PII_UNMASKED | merge_dim_customer.sql | PII column 'email' appears unmasked in DML for non-staging table 'dim_customer' | Apply masking: SHA256(CAST(email AS BYTES)) or use BigQuery column-level policy tags |
| WARNING | PII_UNMASKED | merge_dim_customer.sql | PII column 'phone' appears unmasked in DML for non-staging table 'dim_customer' | Apply masking: SHA256(CAST(phone AS BYTES)) or use BigQuery column-level policy tags |
| WARNING | PII_UNMASKED | merge_dim_customer.sql | PII column 'address_line1' appears unmasked in DML for non-staging table 'dim_customer' | Apply masking: SHA256(CAST(address_line1 AS BYTES)) or use BigQuery column-level policy tags |

**Stats:**
- files_scanned: 12
- secret_patterns_checked: 7
- pii_columns_checked: 5
- critical_count: 0
- warning_count: 5
