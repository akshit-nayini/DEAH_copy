# AgenticHub MySQL — Team DB Setup

## Connection details

| Field | Value |
|---|---|
| Instance | `verizon-data:us-central1:mysql-druid-metadatastore` |
| Database | `agentichub` |
| User | `sa` |
| Tables | `EMPLOYEES` |

---

## One-time setup

**1. Install packages**
```bash
pip install "cloud-sql-python-connector[pymysql]" sqlalchemy pandas
```

**2. Add the GCP key file**  
Place the team's `gcp.env` file in this folder (`db_setup/`).  
It should contain:
```
export GOOGLE_APPLICATION_CREDENTIALS="C:\path\to\verizon-data-key.json"
```
The JSON key file must also exist at that path.

**3. Test your connection**
```bash
cd db_setup
python mysql_connector.py
```

Expected output:
```
Connected    : OK
Tables       : ['EMPLOYEES']
EMPLOYEES    : 14 columns
Result       : PASS
```

---

## Usage in Python

```python
from mysql_connector import run_query, get_employees, get_schema

# Fetch all employees
df = get_employees()

# Custom query
df = run_query("SELECT * FROM EMPLOYEES WHERE JOB_ID = %s", ("IT_PROG",))

# Get column schema
df = get_schema()
print(df[["column_name", "data_type", "is_nullable"]])
```

## EMPLOYEES columns

| Column | Type |
|---|---|
| EMPLOYEE_ID | int |
| FIRST_NAME | varchar |
| LAST_NAME | varchar |
| EMAIL | varchar |
| PHONE_NUMBER | varchar |
| HIRE_DATE | date |
| JOB_ID | varchar |
| SALARY | decimal |
| COMMISSION_PCT | decimal |
| MANAGER_ID | int |
| DEPARTMENT_ID | int |
| STATUS | varchar |
| CREATED_DATE | datetime |
| UPDATED_DATE | datetime |
