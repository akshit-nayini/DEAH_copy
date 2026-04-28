"""
generator_agent.py
------------------
Pure Python synthetic data generator — no LLM required.

Generates sensible realistic data purely from:
    - column name   (e.g. email, first_name, salary, hire_date)
    - BQ data type  (INT64, STRING, NUMERIC, DATE, TIMESTAMP, BOOL)
    - notes         (extra semantic hints)
    - transformation_logic (e.g. CAST(EMAIL AS STRING))

Column name pattern matching covers the most common data domains:
    Identity   : employee_id, customer_id, order_id, user_id ...
    Name       : first_name, last_name, full_name ...
    Contact    : email, phone, phone_number ...
    Address    : address, street, city, state, country, zip ...
    Date/Time  : hire_date, created_date, updated_date, birth_date ...
    Finance    : salary, amount, price, revenue, cost, commission_pct ...
    Status     : status, state, type, category, gender ...
    Codes      : job_id, department_id, manager_id, code, ref ...
    Text       : name, description, notes, comment, title ...
    Boolean    : is_*, has_*, active, enabled, flag ...

Falls back to type-appropriate random data for unrecognised column names.
"""

import random
import string
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List


# ── Seed for reproducibility ───────────────────────────────────────────────────
_RNG = random.Random()


def set_seed(seed: int) -> None:
    _RNG.seed(seed)


# ── Data pools ─────────────────────────────────────────────────────────────────

FIRST_NAMES = [
    "James", "Mary", "John", "Patricia", "Robert", "Jennifer", "Michael",
    "Linda", "William", "Barbara", "David", "Susan", "Richard", "Jessica",
    "Joseph", "Sarah", "Thomas", "Karen", "Charles", "Lisa", "Aisha", "Mohamed",
    "Priya", "Rahul", "Emma", "Oliver", "Sophia", "Liam", "Isabella", "Noah",
    "Fatima", "Ali", "Chen", "Wei", "Yuki", "Kenji", "Amara", "Kofi",
    "Sofia", "Mateus", "Ana", "Carlos", "Elena", "Ivan", "Natasha", "Ravi",
]

LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
    "Davis", "Rodriguez", "Martinez", "Wilson", "Anderson", "Taylor", "Thomas",
    "Hernandez", "Moore", "Martin", "Jackson", "Thompson", "White", "Khan",
    "Patel", "Kumar", "Singh", "Chen", "Wang", "Kim", "Park", "Nguyen",
    "Tanaka", "Sato", "Okafor", "Mensah", "Diallo", "Nkosi", "Silva",
    "Santos", "Ferreira", "Oliveira", "Mueller", "Schmidt", "Fischer",
]

EMAIL_DOMAINS = [
    "company.com", "corp.org", "enterprise.net", "business.io",
    "acme.com", "globaltech.com", "dataworks.net", "solutions.org",
]

STREETS = [
    "Main St", "Oak Ave", "Maple Dr", "Cedar Ln", "Pine Rd", "Elm St",
    "Washington Blvd", "Park Ave", "Lake Dr", "River Rd", "Hill St",
    "Forest Way", "Valley Rd", "Summit Dr", "Harbor Blvd",
]

CITIES = [
    "New York", "Los Angeles", "Chicago", "Houston", "Phoenix", "Philadelphia",
    "San Antonio", "San Diego", "Dallas", "San Jose", "Austin", "Jacksonville",
    "London", "Manchester", "Birmingham", "Toronto", "Vancouver", "Sydney",
    "Melbourne", "Berlin", "Paris", "Amsterdam", "Madrid", "Rome",
]

COUNTRIES = ["US", "GB", "CA", "AU", "DE", "FR", "NL", "ES", "IT", "IN", "JP", "SG"]

STATES = ["CA", "TX", "NY", "FL", "IL", "PA", "OH", "GA", "NC", "MI"]

STATUS_VALUES   = ["active", "inactive", "pending", "suspended", "terminated", "on_leave"]
GENDER_VALUES   = ["M", "F", "Male", "Female", "Non-binary", "Other"]
TYPE_VALUES     = ["standard", "premium", "basic", "enterprise", "trial"]
CATEGORY_VALUES = ["A", "B", "C", "D", "E"]

JOB_CODES = [
    "IT_PROG", "IT_MAN", "SA_MAN", "SA_REP", "FI_ACCOUNT", "FI_MGR",
    "HR_REP", "HR_MAN", "MK_MAN", "MK_REP", "AD_ASST", "AD_VP", "AD_PRES",
    "PU_MAN", "PU_CLERK", "ST_MAN", "ST_CLERK", "SH_CLERK",
]

DEPARTMENTS = {
    10: "Administration", 20: "Marketing", 30: "Purchasing",
    40: "Human Resources", 50: "Shipping", 60: "IT",
    70: "Public Relations", 80: "Sales", 90: "Executive",
    100: "Finance", 110: "Accounting",
}

CURRENCIES    = ["USD", "EUR", "GBP", "CAD", "AUD", "JPY", "SGD", "INR"]
PAYMENT_METHODS = ["credit_card", "debit_card", "paypal", "bank_transfer", "cash"]
PRODUCT_CATEGORIES = ["Electronics", "Clothing", "Home & Garden", "Sports", "Books", "Beauty", "Toys"]
LOYALTY_TIERS = ["bronze", "silver", "gold", "platinum"]
SCD_ROLES = ["natural_key", "metadata", "scd_type2", "audit"]


# ── Column name → generator dispatch ──────────────────────────────────────────

def _col_matches(name: str, *keywords) -> bool:
    """Case-insensitive check if column name contains any keyword."""
    n = name.lower()
    return any(kw in n for kw in keywords)


def _generate_by_name_and_type(
    col_name: str,
    base_type: str,
    bq_type: str,
    notes: str,
    from_date: str,
    to_date: str,
    row_index: int,
) -> Any:
    """
    Generate a sensible value based on column name + BQ type + notes.
    row_index is used to ensure uniqueness for ID-like columns.
    """
    name = col_name.lower()
    notes_lower = notes.lower() if notes else ""

    # ── Boolean ───────────────────────────────────────────────────────────────
    if base_type == "boolean":
        return _RNG.choice([True, False])

    # ── Date / Datetime ───────────────────────────────────────────────────────
    if base_type in ("date", "datetime"):
        return _random_date(from_date, to_date, base_type)

    # ── Integer ───────────────────────────────────────────────────────────────
    if base_type == "integer":
        # Primary key / ID columns — unique sequential
        if _col_matches(name, "employee_id", "emp_id") and "primary" in notes_lower:
            return 1000 + row_index
        if _col_matches(name, "_id", "id") and not _col_matches(name, "manager", "parent", "ref"):
            return _RNG.randint(1000, 99999)
        # Manager / foreign key ID — nullable sometimes
        if _col_matches(name, "manager_id", "parent_id", "supervisor"):
            return _RNG.randint(1000, 9999) if _RNG.random() > 0.1 else None
        # Department
        if _col_matches(name, "department_id", "dept_id"):
            return _RNG.choice(list(DEPARTMENTS.keys()))
        # Quantity
        if _col_matches(name, "quantity", "qty", "count", "units"):
            return _RNG.randint(1, 50)
        # Age
        if _col_matches(name, "age"):
            return _RNG.randint(18, 65)
        # Year
        if _col_matches(name, "year"):
            return _RNG.randint(2018, 2026)
        # Generic integer
        return _RNG.randint(1, 9999)

    # ── Float / Numeric ───────────────────────────────────────────────────────
    if base_type == "float":
        # Salary
        if _col_matches(name, "salary", "wage", "compensation", "pay"):
            return round(_RNG.uniform(30000, 250000), 2)
        # Commission / percentage / rate
        if _col_matches(name, "commission_pct", "commission", "rate", "pct", "percent"):
            return round(_RNG.uniform(0.0, 0.40), 2) if _RNG.random() > 0.2 else None
        # Price / amount / cost / revenue
        if _col_matches(name, "price", "amount", "cost", "revenue", "total", "value"):
            return round(_RNG.uniform(10.0, 5000.0), 2)
        # Tax / discount
        if _col_matches(name, "tax", "discount"):
            return round(_RNG.uniform(0.0, 30.0), 2)
        # Weight / size
        if _col_matches(name, "weight", "size", "length", "width", "height"):
            return round(_RNG.uniform(0.1, 500.0), 2)
        # Generic float
        return round(_RNG.uniform(0.0, 1000.0), 2)

    # ── String ────────────────────────────────────────────────────────────────
    if base_type == "string":

        # --- Identity / ID patterns ---
        if _col_matches(name, "order_id"):
            return "ORD-" + str(10000 + row_index).zfill(5)
        if _col_matches(name, "customer_id", "cust_id"):
            return "CUST-" + str(_RNG.randint(1000, 9999))
        if _col_matches(name, "employee_id", "emp_id"):
            return "EMP-" + str(1000 + row_index)
        if _col_matches(name, "invoice_id", "inv_id"):
            return "INV-" + str(_RNG.randint(10000, 99999))
        if _col_matches(name, "product_id", "prod_id", "item_id"):
            return "PRD-" + str(_RNG.randint(100, 9999))
        if _col_matches(name, "_uuid", "guid"):
            return str(uuid.uuid4())

        # --- Names ---
        if _col_matches(name, "first_name", "firstname", "given_name"):
            return _RNG.choice(FIRST_NAMES)
        if _col_matches(name, "last_name", "lastname", "surname", "family_name"):
            return _RNG.choice(LAST_NAMES)
        if _col_matches(name, "full_name", "fullname", "display_name"):
            return _RNG.choice(FIRST_NAMES) + " " + _RNG.choice(LAST_NAMES)
        if _col_matches(name, "name") and not _col_matches(name, "username", "user_name"):
            if "department" in name or "dept" in name:
                return _RNG.choice(list(DEPARTMENTS.values()))
            if "company" in name or "org" in name or "business" in name:
                return _RNG.choice(LAST_NAMES) + " " + _RNG.choice(["Corp", "Inc", "Ltd", "Group"])
            return _RNG.choice(FIRST_NAMES) + " " + _RNG.choice(LAST_NAMES)

        # --- Contact ---
        if _col_matches(name, "email", "email_address", "e_mail"):
            fn = _RNG.choice(FIRST_NAMES).lower()
            ln = _RNG.choice(LAST_NAMES).lower()
            domain = _RNG.choice(EMAIL_DOMAINS)
            return fn + "." + ln + "@" + domain
        if _col_matches(name, "phone", "mobile", "cell", "telephone", "phone_number"):
            return "+1-" + str(_RNG.randint(200, 999)) + "-" + str(_RNG.randint(100, 999)) + "-" + str(_RNG.randint(1000, 9999))
        if _col_matches(name, "username", "user_name", "login"):
            return _RNG.choice(FIRST_NAMES).lower() + str(_RNG.randint(10, 999))

        # --- Address ---
        if _col_matches(name, "street", "address_line", "shipping_address", "billing_address", "address"):
            return str(_RNG.randint(1, 9999)) + " " + _RNG.choice(STREETS)
        if _col_matches(name, "city"):
            return _RNG.choice(CITIES)
        if _col_matches(name, "state", "province", "region") and "status" not in name:
            return _RNG.choice(STATES)
        if _col_matches(name, "country", "country_code"):
            return _RNG.choice(COUNTRIES)
        if _col_matches(name, "zip", "postal", "postcode"):
            return str(_RNG.randint(10000, 99999))

        # --- Status / Type / Category ---
        if _col_matches(name, "status"):
            return _RNG.choice(STATUS_VALUES)
        if _col_matches(name, "gender", "sex"):
            return _RNG.choice(["M", "F"])
        if _col_matches(name, "loyalty_tier", "tier", "level", "grade"):
            return _RNG.choice(LOYALTY_TIERS)
        if _col_matches(name, "payment_method", "payment_type"):
            return _RNG.choice(PAYMENT_METHODS)
        if _col_matches(name, "currency", "currency_code"):
            return _RNG.choice(CURRENCIES)
        if _col_matches(name, "product_category", "category"):
            return _RNG.choice(PRODUCT_CATEGORIES)
        if _col_matches(name, "account_status", "account_state"):
            return _RNG.choice(["active", "inactive", "suspended"])
        if _col_matches(name, "scd_role"):
            return _RNG.choice(SCD_ROLES)
        if _col_matches(name, "type") and not _col_matches(name, "data_type"):
            return _RNG.choice(TYPE_VALUES)

        # --- Codes / References ---
        if _col_matches(name, "job_id", "job_code", "position"):
            return _RNG.choice(JOB_CODES)
        if _col_matches(name, "department_name", "dept_name"):
            return _RNG.choice(list(DEPARTMENTS.values()))
        if _col_matches(name, "source_system", "system"):
            return _RNG.choice(["Oracle HR", "SAP", "Workday", "MySQL", "Salesforce"])
        if _col_matches(name, "source_table", "table_name"):
            return _RNG.choice(["EMPLOYEES", "ORDERS", "CUSTOMERS", "PRODUCTS"])

        # --- Description / Notes / Text ---
        if _col_matches(name, "description", "desc", "notes", "comment", "remarks", "details"):
            templates = [
                "Standard record for processing",
                "Auto-generated synthetic entry",
                "Validated and approved",
                "Pending review",
                "Active record in good standing",
            ]
            return _RNG.choice(templates)
        if _col_matches(name, "title", "heading"):
            return _RNG.choice(["Manager", "Analyst", "Engineer", "Director", "Specialist", "Lead"])
        if _col_matches(name, "url", "link", "website"):
            return "https://www." + _RNG.choice(LAST_NAMES).lower() + ".com"

        # --- Flags / Codes ---
        if _col_matches(name, "code", "ref", "reference", "batch_id", "batch"):
            return "".join(_RNG.choices(string.ascii_uppercase + string.digits, k=8))
        if _col_matches(name, "source_system"):
            return _RNG.choice(["Oracle", "SAP", "MySQL", "Postgres"])

        # --- Generic string fallback ---
        return "".join(_RNG.choices(string.ascii_letters, k=_RNG.randint(6, 12)))

    # ── Fallback for any unhandled type ───────────────────────────────────────
    return str(_RNG.randint(1, 9999))


# ── Date helper ────────────────────────────────────────────────────────────────

def _random_date(from_date: str, to_date: str, base_type: str) -> str:
    """Generate a random date/datetime string within the given range."""
    try:
        dt_min = datetime.strptime(from_date, "%Y-%m-%d")
        dt_max = datetime.strptime(to_date, "%Y-%m-%d")
        if base_type == "datetime":
            dt_max = dt_max.replace(hour=23, minute=59, second=59)
        delta = int((dt_max - dt_min).total_seconds())
        if delta <= 0:
            result = dt_min
        else:
            result = dt_min + timedelta(seconds=_RNG.randint(0, delta))
        if base_type == "date":
            return result.strftime("%Y-%m-%d")
        return result.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return from_date


# ── Main row generator ─────────────────────────────────────────────────────────

def generate_rows(
    profile: List[Dict],
    table_name: str,
    num_records: int,
    from_date: str,
    to_date: str,
    **kwargs,               # absorbs llm= and batch_size= if passed — ignored here
) -> List[Dict[str, Any]]:
    """
    Generate num_records synthetic rows using pure Python logic.

    Parameters
    ----------
    profile     : column profile from schema_builder.build_profile()
    table_name  : BQ target table name (used for logging)
    num_records : total rows to generate
    from_date   : start of date range (YYYY-MM-DD)
    to_date     : end of date range (YYYY-MM-DD)
    **kwargs    : ignored (absorbs llm= batch_size= for API compatibility)

    Returns
    -------
    List of row dicts — keys = column names from mapping.
    """
    ordered = sorted(profile, key=lambda c: c["ordinal"])
    rows = []

    print("    Generating " + str(num_records) + " rows (pure Python)...")

    for i in range(num_records):
        row = {}
        for col in ordered:
            value = _generate_by_name_and_type(
                col_name   = col["name"],
                base_type  = col["base_type"],
                bq_type    = col["bq_type"],
                notes      = col.get("notes", ""),
                from_date  = from_date,
                to_date    = to_date,
                row_index  = i,
            )
            row[col["name"]] = value
        rows.append(row)

    print("    Done — " + str(len(rows)) + " rows generated")
    return rows
