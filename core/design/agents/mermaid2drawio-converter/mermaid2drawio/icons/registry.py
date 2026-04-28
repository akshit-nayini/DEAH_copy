"""
Icon Registry - Maps service/tool names to Draw.io styles with embedded SVG icons.

Instead of using stencil library shapes, this registry generates inline SVG icons
(100x100 pixels) encoded as base64 data URIs. Each service gets a branded colored
icon with a distinctive shape matching its category (cloud, database, storage, etc.)
with abbreviation text, providing consistent, colorful diagrams.
"""

from typing import Optional, Dict
import re
import base64


class IconRegistry:
    """
    Registry mapping service/tool keywords to Draw.io style strings with embedded SVG.

    Each service is assigned a brand color, abbreviation, and category. The SVG icon is
    a 100x100 pixel shape (cloud, database, storage bucket, etc.) with the service color
    background and white symbol text.
    """

    # Service name → (brand_color, abbreviation, category) mapping
    SERVICE_ICONS: Dict[str, tuple[str, str, str]] = {
        # Google Cloud Platform
        "gcs": ("#4285F4", "GCS", "storage"),
        "google cloud storage": ("#4285F4", "GCS", "storage"),
        "cloud storage": ("#4285F4", "GCS", "storage"),
        "bigquery": ("#4285F4", "BQ", "database"),
        "big query": ("#4285F4", "BQ", "database"),
        "bq": ("#4285F4", "BQ", "database"),
        "dataflow": ("#4285F4", "DF", "processing"),
        "cloud dataflow": ("#4285F4", "DF", "processing"),
        "beam": ("#4285F4", "BM", "processing"),
        "apache beam": ("#4285F4", "BM", "processing"),
        "beam job": ("#4285F4", "BM", "processing"),
        "streaming beam job": ("#4285F4", "BM", "processing"),
        "batch beam job": ("#4285F4", "BM", "processing"),
        "dataproc": ("#4285F4", "DP", "processing"),
        "cloud dataproc": ("#4285F4", "DP", "processing"),
        "pubsub": ("#4285F4", "PS", "messaging"),
        "pub/sub": ("#4285F4", "PS", "messaging"),
        "cloud pub/sub": ("#4285F4", "PS", "messaging"),
        "cloud functions": ("#4285F4", "GCF", "processing"),
        "gcf": ("#4285F4", "GCF", "processing"),
        "cloud run": ("#4285F4", "CR", "processing"),
        "gke": ("#4285F4", "GKE", "processing"),
        "kubernetes engine": ("#4285F4", "GKE", "processing"),
        "gce": ("#4285F4", "GCE", "processing"),
        "compute engine": ("#4285F4", "GCE", "processing"),
        "cloud sql": ("#4285F4", "SQL", "database"),
        "cloudsql": ("#4285F4", "SQL", "database"),
        "cloud spanner": ("#4285F4", "SPN", "database"),
        "spanner": ("#4285F4", "SPN", "database"),
        "firestore": ("#FFCA28", "FS", "database"),
        "cloud firestore": ("#FFCA28", "FS", "database"),
        "bigtable": ("#4285F4", "BT", "database"),
        "cloud bigtable": ("#4285F4", "BT", "database"),
        "composer": ("#4285F4", "CC", "orchestration"),
        "cloud composer": ("#4285F4", "CC", "orchestration"),
        "cloud cdn": ("#4285F4", "CDN", "processing"),
        "cloud dns": ("#4285F4", "DNS", "processing"),
        "cloud armor": ("#4285F4", "ARM", "processing"),
        "vpc": ("#4285F4", "VPC", "processing"),
        "cloud load balancing": ("#4285F4", "LB", "processing"),
        "load balancer": ("#4285F4", "LB", "processing"),
        "cloud logging": ("#4285F4", "LOG", "monitoring"),
        "stackdriver": ("#4285F4", "LOG", "monitoring"),
        "cloud monitoring": ("#4285F4", "MON", "monitoring"),
        "vertex ai": ("#4285F4", "VAI", "processing"),
        "ai platform": ("#4285F4", "VAI", "processing"),
        "cloud iam": ("#4285F4", "IAM", "processing"),
        "iam": ("#4285F4", "IAM", "processing"),
        "secret manager": ("#4285F4", "SM", "processing"),
        "artifact registry": ("#4285F4", "AR", "processing"),
        "cloud build": ("#4285F4", "CB", "processing"),
        "memorystore": ("#4285F4", "MEM", "database"),
        "datastore": ("#4285F4", "DS", "database"),
        "cloud scheduler": ("#4285F4", "SCH", "orchestration"),
        "cloud tasks": ("#4285F4", "TSK", "processing"),
        "apigee": ("#4285F4", "API", "processing"),
        "api gateway": ("#4285F4", "API", "processing"),

        # Amazon Web Services
        "s3": ("#569A31", "S3", "storage"),
        "aws s3": ("#569A31", "S3", "storage"),
        "ec2": ("#FF9900", "EC2", "processing"),
        "aws ec2": ("#FF9900", "EC2", "processing"),
        "lambda": ("#FF9900", "λ", "processing"),
        "aws lambda": ("#FF9900", "λ", "processing"),
        "rds": ("#3B48CC", "RDS", "database"),
        "aws rds": ("#3B48CC", "RDS", "database"),
        "dynamodb": ("#4053D6", "DDB", "database"),
        "sqs": ("#FF9900", "SQS", "messaging"),
        "sns": ("#FF4F8B", "SNS", "messaging"),
        "kinesis": ("#FF9900", "KIN", "messaging"),
        "redshift": ("#8C4FFF", "RS", "database"),
        "athena": ("#8C4FFF", "ATH", "database"),
        "glue": ("#8C4FFF", "GLU", "processing"),
        "emr": ("#FF9900", "EMR", "processing"),
        "ecs": ("#FF9900", "ECS", "processing"),
        "eks": ("#FF9900", "EKS", "processing"),
        "fargate": ("#FF9900", "FAR", "processing"),
        "cloudfront": ("#FF9900", "CF", "processing"),
        "route 53": ("#FF9900", "R53", "processing"),
        "cloudwatch": ("#FF4F8B", "CW", "monitoring"),
        "step functions": ("#FF9900", "SF", "orchestration"),
        "eventbridge": ("#FF9900", "EB", "messaging"),
        "cognito": ("#FF9900", "COG", "processing"),
        "elasticache": ("#FF9900", "EC", "database"),
        "aurora": ("#FF9900", "AUR", "database"),
        "sagemaker": ("#FF9900", "SM", "processing"),
        "ecr": ("#FF9900", "ECR", "storage"),
        "codepipeline": ("#FF9900", "CP", "orchestration"),
        "codebuild": ("#FF9900", "CB", "processing"),

        # Microsoft Azure
        "azure blob": ("#0089D6", "BLB", "storage"),
        "blob storage": ("#0089D6", "BLB", "storage"),
        "azure sql": ("#0089D6", "SQL", "database"),
        "cosmos db": ("#0089D6", "CDB", "database"),
        "cosmosdb": ("#0089D6", "CDB", "database"),
        "azure functions": ("#0089D6", "FN", "processing"),
        "azure vm": ("#0089D6", "VM", "processing"),
        "azure aks": ("#0089D6", "AKS", "processing"),
        "azure devops": ("#0089D6", "ADevOps", "orchestration"),
        "azure data factory": ("#0089D6", "ADF", "orchestration"),
        "data factory": ("#0089D6", "ADF", "orchestration"),
        "azure synapse": ("#0089D6", "SYN", "processing"),
        "synapse": ("#0089D6", "SYN", "processing"),
        "azure databricks": ("#0089D6", "DBX", "processing"),
        "azure event hub": ("#0089D6", "EH", "messaging"),
        "event hub": ("#0089D6", "EH", "messaging"),
        "azure service bus": ("#0089D6", "SB", "messaging"),
        "service bus": ("#0089D6", "SB", "messaging"),
        "azure key vault": ("#0089D6", "KV", "processing"),
        "key vault": ("#0089D6", "KV", "processing"),
        "azure monitor": ("#0089D6", "MON", "monitoring"),
        "azure cdn": ("#0089D6", "CDN", "processing"),
        "azure active directory": ("#0089D6", "AAD", "processing"),
        "azure ad": ("#0089D6", "AAD", "processing"),
        "azure logic apps": ("#0089D6", "LA", "orchestration"),
        "logic apps": ("#0089D6", "LA", "orchestration"),
        "power bi": ("#F2C811", "PBI", "generic"),

        # Third-party / SaaS services
        "salesforce": ("#00A1E0", "SF", "cloud"),
        "sfdc": ("#00A1E0", "SF", "cloud"),
        "salesforce crm": ("#00A1E0", "SF", "cloud"),
        "shopify": ("#96BF48", "SH", "cloud"),
        "zendesk": ("#03363D", "ZD", "cloud"),
        "hubspot": ("#FF7A59", "HS", "cloud"),
        "marketo": ("#5C4C9F", "MK", "cloud"),
        "kafka": ("#231F20", "KFK", "messaging"),
        "apache kafka": ("#231F20", "KFK", "messaging"),
        "elasticsearch": ("#FEC514", "ES", "database"),
        "elastic": ("#FEC514", "ES", "database"),
        "mongodb": ("#47A248", "MDB", "database"),
        "mongo": ("#47A248", "MDB", "database"),
        "redis": ("#DC382D", "RDS", "database"),
        "postgresql": ("#336791", "PG", "database"),
        "postgres": ("#336791", "PG", "database"),
        "mysql": ("#4479A1", "SQL", "database"),
        "docker": ("#2496ED", "DKR", "processing"),
        "kubernetes": ("#326CE5", "K8S", "processing"),
        "k8s": ("#326CE5", "K8S", "processing"),
        "terraform": ("#7B42BC", "TF", "orchestration"),
        "jenkins": ("#D24939", "JNK", "orchestration"),
        "github": ("#24292E", "GH", "orchestration"),
        "gitlab": ("#FC6D26", "GL", "orchestration"),
        "jira": ("#0052CC", "JIRA", "generic"),
        "confluence": ("#003366", "CONF", "generic"),
        "slack": ("#4A154B", "SLK", "generic"),
        "grafana": ("#F46800", "GRF", "monitoring"),
        "prometheus": ("#E6522C", "PRO", "monitoring"),
        "airflow": ("#017CEE", "AF", "orchestration"),
        "apache airflow": ("#017CEE", "AF", "orchestration"),
        "spark": ("#E25A1C", "SPK", "processing"),
        "apache spark": ("#E25A1C", "SPK", "processing"),
        "pyspark": ("#E25A1C", "SPK", "processing"),
        "snowflake": ("#29B5E8", "SNF", "database"),
        "databricks": ("#FF3621", "DBX", "processing"),
        "tableau": ("#E97627", "TAB", "generic"),
        "looker": ("#4285F4", "LKR", "generic"),
        "looker studio": ("#4285F4", "LKR", "generic"),
        "looker studio / looker": ("#4285F4", "LKR", "generic"),
        "dbt": ("#FF694B", "dbt", "orchestration"),
        "nginx": ("#009639", "NGX", "processing"),
        "rabbitmq": ("#FF6600", "RMQ", "messaging"),
        "oracle": ("#F80000", "ORA", "database"),
        "sap": ("#0FAAFF", "SAP", "cloud"),
        "twilio": ("#F22F46", "TWL", "cloud"),
        "stripe": ("#635BFF", "STP", "cloud"),
        "sendgrid": ("#1BA1E2", "SG", "cloud"),
        "auth0": ("#EB5424", "A0", "cloud"),
        "okta": ("#007DC1", "OKT", "cloud"),
        "datadog": ("#632CA6", "DD", "monitoring"),
        "splunk": ("#000000", "SPL", "monitoring"),
        "newrelic": ("#1CE783", "NR", "monitoring"),
        "new relic": ("#1CE783", "NR", "monitoring"),
        "pagerduty": ("#06AC38", "PD", "monitoring"),
        "dead letter": ("#B71C1C", "DL", "storage"),
        "dead-letter": ("#B71C1C", "DL", "storage"),
    }

    def __init__(self):
        """Initialize the combined lookup table (all lowercase keys)."""
        self._lookup: Dict[str, tuple[str, str, str]] = {}
        for key, val in self.SERVICE_ICONS.items():
            self._lookup[key.lower()] = val

    def resolve(self, label: str) -> Optional[tuple[str, str, str]]:
        """
        Given a node label from a Mermaid diagram, return the best-matching
        (color, abbreviation, category) tuple. Returns None if no match found.

        IMPORTANT: Only matches when the FIRST LINE of the label (the primary
        name) is a known service/tool. This prevents false positives like
        "DAG: salesforce_ingest" matching the Salesforce icon.

        Matching strategies (in order):
        1. Exact match on the full first line
        2. gs:// prefix → GCS storage icon
        3. Known keyword starts the first line
        4. Known keyword contained in first line (with length threshold)
        5. Return None
        """
        # Strip surrounding quotes
        clean_label = label.strip().strip('"').strip("'")

        # Use ONLY the first line for matching
        first_line = clean_label.split("\\n")[0].split("\n")[0].strip()

        # Skip labels that are clearly prefixed descriptions, not service names
        # E.g., "DAG: salesforce_ingest", "Dataset: stg_", "Step 1: Schema Validation"
        skip_prefixes = ("dag:", "step ", "dataset:")
        first_lower = first_line.lower().strip()
        for prefix in skip_prefixes:
            if first_lower.startswith(prefix):
                return None

        # Special: "gs://..." always maps to GCS
        if first_lower.startswith("gs://"):
            return self._lookup.get("gcs")

        # Special: "Dead-Letter Bucket" / "Dead Letter"
        if "dead" in first_line.lower() and "letter" in first_line.lower():
            return self._lookup.get("dead-letter") or self._lookup.get("dead letter")

        # Clean for matching
        cleaned = re.sub(r"[^a-z0-9 /.]", " ", first_line.lower()).strip()
        cleaned = re.sub(r"\s+", " ", cleaned)  # collapse whitespace

        # 1. Exact match on full first line
        if cleaned in self._lookup:
            return self._lookup[cleaned]

        # 2. Try matching longest keywords first
        sorted_keys = sorted(self._lookup.keys(), key=len, reverse=True)
        for keyword in sorted_keys:
            if len(keyword) < 2:
                continue
            if keyword == cleaned:
                return self._lookup[keyword]
            # Keyword starts the first line (e.g., "Terraform 1.8+" → "terraform")
            if cleaned.startswith(keyword) and len(keyword) >= len(cleaned) * 0.4:
                return self._lookup[keyword]
            # First line starts with keyword words
            words = cleaned.split()
            kw_words = keyword.split()
            if len(kw_words) >= 1 and words[:len(kw_words)] == kw_words:
                return self._lookup[keyword]

        # 3. Check if any keyword is contained within first line
        #    but require keyword to be at least 4 chars to avoid false matches
        for keyword in sorted_keys:
            if len(keyword) < 4:
                continue
            if keyword in cleaned and len(keyword) >= len(cleaned) * 0.3:
                return self._lookup[keyword]

        return None

    def is_icon_node(self, label: str) -> bool:
        """Return True if the label resolves to an actual service icon (not fallback)."""
        return self.resolve(label) is not None

    def _generate_svg_icon(self, bg_color: str, symbol_text: str, category: str) -> str:
        """
        Generate a 100x100 SVG icon with a shape matching the category.
        Categories:
        - cloud: Cloud shape with abbreviation
        - database: Cylinder/database shape
        - storage: Bucket shape (trapezoid with lines)
        - processing: Chevron/arrow pipeline shapes
        - orchestration: Connected nodes/workflow shape
        - messaging: Envelope/queue shape
        - monitoring: Generic rounded rect
        - generic: Rounded rect with abbreviation

        Returns base64-encoded SVG string.
        """
        # Adjust font size based on text length
        if len(symbol_text) <= 2:
            font_size = 18
        elif len(symbol_text) <= 3:
            font_size = 16
        else:
            font_size = 14

        svg = ""

        if category == "cloud":
            # Cloud shape with abbreviation
            svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
  <rect x="5" y="5" width="90" height="90" rx="12" fill="{bg_color}"/>
  <path d="M25 55c0-8 6-14 14-14 2-6 8-11 15-11s13 5 15 11c8 0 14 6 14 14s-6 14-14 14H39c-8 0-14-6-14-14z" fill="white"/>
  <text x="50" y="62" text-anchor="middle" fill="{bg_color}" font-size="{font_size}" font-weight="bold" font-family="Arial, sans-serif">{symbol_text}</text>
</svg>'''

        elif category == "database":
            # Cylinder/database shape
            svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
  <rect x="5" y="5" width="90" height="90" rx="12" fill="{bg_color}"/>
  <ellipse cx="50" cy="30" rx="18" ry="10" fill="white"/>
  <rect x="32" y="30" width="36" height="30" fill="white" opacity="0.9"/>
  <ellipse cx="50" cy="60" rx="18" ry="10" fill="white" opacity="0.8"/>
  <text x="50" y="50" text-anchor="middle" fill="{bg_color}" font-size="{font_size}" font-weight="bold" font-family="Arial, sans-serif">{symbol_text}</text>
</svg>'''

        elif category == "storage":
            # Bucket shape (trapezoid with lines)
            svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
  <rect x="5" y="5" width="90" height="90" rx="12" fill="{bg_color}"/>
  <path d="M30 30h40l-5 45H35z" fill="white" opacity="0.9"/>
  <rect x="28" y="28" width="44" height="8" rx="2" fill="white"/>
  <line x1="40" y1="45" x2="40" y2="65" stroke="{bg_color}" stroke-width="2"/>
  <line x1="50" y1="45" x2="50" y2="65" stroke="{bg_color}" stroke-width="2"/>
  <line x1="60" y1="45" x2="60" y2="65" stroke="{bg_color}" stroke-width="2"/>
  <text x="50" y="78" text-anchor="middle" fill="{bg_color}" font-size="{font_size - 2}" font-weight="bold" font-family="Arial, sans-serif">{symbol_text}</text>
</svg>'''

        elif category == "processing":
            # Chevron/arrow pipeline shapes
            svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
  <rect x="5" y="5" width="90" height="90" rx="12" fill="{bg_color}"/>
  <path d="M20 35h25l10 15-10 15H20z" fill="white" opacity="0.9"/>
  <path d="M50 35h25l10 15-10 15H50z" fill="white" opacity="0.7"/>
  <circle cx="75" cy="50" r="3" fill="white"/>
  <text x="37" y="60" text-anchor="middle" fill="{bg_color}" font-size="{font_size - 2}" font-weight="bold" font-family="Arial, sans-serif">{symbol_text}</text>
</svg>'''

        elif category == "orchestration":
            # Connected nodes/workflow shape (DAG/pipeline nodes)
            svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
  <rect x="5" y="5" width="90" height="90" rx="12" fill="{bg_color}"/>
  <circle cx="35" cy="35" r="8" fill="white"/>
  <circle cx="65" cy="35" r="8" fill="white"/>
  <circle cx="50" cy="60" r="8" fill="white"/>
  <line x1="40" y1="39" x2="55" y2="55" stroke="white" stroke-width="3"/>
  <line x1="60" y1="39" x2="55" y2="55" stroke="white" stroke-width="3"/>
  <path d="M50 68v10" stroke="white" stroke-width="3" stroke-linecap="round"/>
  <path d="M45 78l5 5 5-5" stroke="white" stroke-width="2" fill="none"/>
  <text x="50" y="85" text-anchor="middle" fill="{bg_color}" font-size="{font_size - 4}" font-weight="bold" font-family="Arial, sans-serif">{symbol_text}</text>
</svg>'''

        elif category == "messaging":
            # Envelope/queue shape
            svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
  <rect x="5" y="5" width="90" height="90" rx="12" fill="{bg_color}"/>
  <rect x="25" y="30" width="50" height="40" fill="white" stroke="white" stroke-width="2"/>
  <path d="M25 30l25 20 25-20" fill="none" stroke="white" stroke-width="2"/>
  <line x1="25" y1="35" x2="50" y2="50" stroke="white" stroke-width="2"/>
  <line x1="75" y1="35" x2="50" y2="50" stroke="white" stroke-width="2"/>
  <text x="50" y="80" text-anchor="middle" fill="{bg_color}" font-size="{font_size - 2}" font-weight="bold" font-family="Arial, sans-serif">{symbol_text}</text>
</svg>'''

        else:
            # Generic rounded rect (fallback for "monitoring", "generic", or unknown)
            svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
  <rect x="5" y="5" width="90" height="90" rx="12" fill="{bg_color}"/>
  <text x="50" y="60" text-anchor="middle" fill="white" font-size="{font_size}" font-weight="bold" font-family="Arial, sans-serif">{symbol_text}</text>
</svg>'''

        # Encode to base64
        svg_bytes = svg.encode('utf-8')
        b64_bytes = base64.b64encode(svg_bytes)
        b64_str = b64_bytes.decode('utf-8')
        return b64_str

    def get_style_for_node(
        self,
        label: str,
        width: int = 80,
        height: int = 80,
        is_icon: bool = True,
    ) -> str:
        """
        Build a complete Draw.io style string for a node. If the label resolves
        to a known service, returns embedded SVG style. Otherwise returns a
        generic rounded rectangle style.
        """
        resolved = self.resolve(label)

        if resolved is None:
            # Generic box — label inside
            return (
                "rounded=1;whiteSpace=wrap;html=1;"
                "fillColor=#dae8fc;strokeColor=#6c8ebf;"
            )

        # Generate SVG icon with service color, abbreviation, and category
        bg_color, symbol, category = resolved
        b64_svg = self._generate_svg_icon(bg_color, symbol, category)

        # Return style with embedded SVG data URI (comma-separated, NOT semicolon)
        return (
            "shape=image;verticalLabelPosition=bottom;labelBackgroundColor=none;"
            "verticalAlign=top;aspect=fixed;imageAspect=0;html=1;"
            "fontSize=10;fontStyle=1;fontColor=#333333;"
            f"image=data:image/svg+xml,{b64_svg}"
        )

    def list_supported_services(self) -> list[str]:
        """Return all supported keyword strings."""
        return sorted(self._lookup.keys())
