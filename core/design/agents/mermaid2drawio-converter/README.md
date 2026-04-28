# mermaid2drawio

Scan Git repositories for Mermaid diagrams and convert them to Draw.io (.drawio) files with actual cloud service icons (GCS, BigQuery, Salesforce, etc.).

##################################################################################################
Requirements:
	Python 3.10+ (only — no external packages needed, everything is standard library)

Two ways to run it:

Option A — Direct (no install):
	cd C:\Users\govindkumar.v\Documents\mermaid2drawio-converter
	python -m mermaid2drawio.cli <repo_path> --output <output_dir> -v
	
Option B — Install as a package (run from anywhere):
	cd C:\Users\govindkumar.v\Documents\mermaid2drawio-converter
	pip install -e .
	mermaid2drawio <repo_path> --output <output_dir> -v
	
Zero external dependencies — it only uses Python's built-in xml.etree, re, base64, argparse, os, pathlib, etc.
So it will work in any Python 3.10+ environment out of the box.

In VS code executed command:

1. To run on entire dire folder -> scan the .mmd , .md files and convert it 
	py -m mermaid2drawio.cli C:\\Users\\shriramkumar.an\\Documents\\git-sample\\DEAH\\de_design\\data_model --output C:\\Users\\shriramkumar.an\\Documents\\git-sample\\DEAH\\de_design\\mermaid2drawio-converter\\drawio_output -v 

2.To run on specific file in a dirctory 
	py -m mermaid2drawio.cli  --file "C:\Users\shriramkumar.an\Documents\git-sample\DEAH\de_design\data_model\output\model_SCRUM-5_20260410_05_er_diagram.mmd" --output "C:\Users\shriramkumar.an\Documents\git-sample\DEAH\de_design\mermaid2drawio-converter\drawio_output\model_SCRUM-5_er_diagram.drawio"

##################################################################################################################################
## Installation

```bash
pip install -e .
```

## Usage

### CLI - Scan a repo
```bash
mermaid2drawio /path/to/repo --output /path/to/output
```

### CLI - Convert a single file
```bash
mermaid2drawio --file architecture.mmd --output architecture.drawio
```

### CLI - List supported icons
```bash
mermaid2drawio --list-icons
```

### Python API
```python
from mermaid2drawio import MermaidToDrawio

converter = MermaidToDrawio(
    repo_path="/path/to/repo",
    output_dir="/path/to/output",
)
results = converter.convert_all()

for r in results:
    print(f"{r.diagram_type.value}: {r.output_path} ({'OK' if r.success else r.error})")
```

## Supported Diagram Types

- **Flowcharts** (`graph`/`flowchart` TB/LR/BT/RL) with subgraphs
- **ER Diagrams** (`erDiagram`) with entities, attributes, and relationships

## Supported Icons

150+ cloud services including GCP (BigQuery, GCS, Dataflow...), AWS (S3, Lambda, EC2...), Azure (Blob, Functions, CosmosDB...), and SaaS tools (Salesforce, Kafka, Snowflake...).
