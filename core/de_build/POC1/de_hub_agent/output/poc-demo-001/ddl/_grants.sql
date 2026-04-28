-- Grant restricted access for PII table: dim_customer
GRANT SELECT ON TABLE `${PROJECT_ID}.${DATASET}.dim_customer`
TO 'group:data-analysts@${ORG_DOMAIN}';

-- Revoke access to PII columns for general analysts
-- Note: Implement column-level security via BigQuery policy tags
-- PII columns requiring policy tags: first_name, last_name, email, phone, address_line1
