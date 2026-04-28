# ScrumTool — Usage Guide

## Setup

Set credentials as environment variables:

```bash
export JIRA_EMAIL="your-email@example.com"
export JIRA_API_KEY="your-jira-api-token"
```

---

## Create the tool

Pass the platform name — `"jira"` is currently supported:

```python
from core.utilities.scrum_tools.base_scurm import ScrumTool

tool = ScrumTool("jira")
```

---

## Operations

### Create a ticket
```python
ticket = tool.create_ticket(
    project_key="SCRUM",
    summary="Fix login bug",
    description="Users cannot log in on mobile.",
    issue_type="Bug",
    priority="High",
    labels=["mobile"],
    attachments=["screenshot.png"],   # optional
)
print(ticket["key"])   # e.g. SCRUM-42
```

### Get a ticket
```python
issue = tool.get_ticket("SCRUM-42")
tool.print_ticket_details(issue)
```

### Update a ticket
```python
tool.update_ticket(
    "SCRUM-42",
    priority="High",
    labels=["mobile", "urgent"],
    attachments=["spec.pdf"],         # optional
)
```

### Add a comment
```python
tool.add_comment(
    "SCRUM-42",
    text="Fix deployed to staging.",
    attachments=["error.log"],        # optional
)
```

### Get comments
```python
comments = tool.get_comments("SCRUM-42")
tool.print_comments(comments)
```

### Upload attachments directly
```python
tool.add_attachment("SCRUM-42", ["diagram.png", "notes.docx"])
```

---

## Adding a new platform

Add an `elif` branch in `ScrumTool.__init__` pointing to the new backend module:

```python
elif platform.lower() == "linear":
    import linear_utility
    self._backend = linear_utility
```

The new module just needs to expose the same function names as `jira_utility.py`.
