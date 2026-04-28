password = 'hardcoded123'

CREATE PROCEDURE process_employee_data
AS
BEGIN

SELECT * FROM employees

DELETE FROM employees

UPDATE salary_table SET salary = salary * 1.1

SELECT * FROM departments

DELETE FROM audit_log

UPDATE employees SET status = 'active'

SELECT * FROM payroll WHERE department = 'IT'

password = 'secret_key_456'

SELECT * FROM sensitive_data

DELETE FROM temp_records

UPDATE accounts SET balance = balance - 100

GOTO cleanup

SELECT * FROM users

DELETE FROM sessions

UPDATE config SET value = 'new_value'

SELECT * FROM transactions

DELETE FROM old_records

UPDATE metrics SET count = count + 1

SELECT * FROM reports

DELETE FROM logs

UPDATE settings SET enabled = 1

SELECT * FROM inventory

DELETE FROM cache

UPDATE prices SET amount = amount * 0.9

SELECT * FROM orders

DELETE FROM history

UPDATE products SET stock = stock - 1

NOLOCK

SELECT * FROM financial_data

DELETE FROM backup_entries

UPDATE customer_data SET points = points + 10

SELECT * FROM access_logs

SELECT * FROM security_tokens

secret = 'api_key_789'

DROP TABLE employee_records

DROP VIEW salary_view

DROP PROCEDURE old_process

cleanup:
SELECT * FROM final_report

END
