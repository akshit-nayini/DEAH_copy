import os
import time
import argparse
import requests
from requests.auth import HTTPBasicAuth
import json

jira_base_url = "https://prodapt-deah.atlassian.net"
email = os.environ.get("JIRA_EMAIL")
api_key = os.environ.get("JIRA_API_KEY")
auth = HTTPBasicAuth(email, api_key)
headers = {"Accept": "application/json"}

_RETRY_STATUSES = {404, 429, 500, 502, 503, 504}
_MAX_RETRIES = 3
_BACKOFF_BASE = 1.5


def _do_request(method: str, url: str, **kwargs) -> requests.Response:
    """Execute an HTTP request, retrying on transient errors with exponential backoff."""
    for attempt in range(_MAX_RETRIES):
        resp = requests.request(method, url, **kwargs)
        if resp.status_code not in _RETRY_STATUSES:
            resp.raise_for_status()
            return resp
        if attempt < _MAX_RETRIES - 1:
            wait = _BACKOFF_BASE * (2 ** attempt)
            print(f"[jira_rw] {resp.status_code} on {url} — retrying in {wait:.1f}s (attempt {attempt + 1}/{_MAX_RETRIES})")
            time.sleep(wait)
    resp.raise_for_status()
    return resp

#This function uploads one or more files as attachments to a Jira ticket
def add_attachment(ticket_id: str, file_paths: list[str]) -> list[dict]:
    url = f"{jira_base_url}/rest/api/3/issue/{ticket_id}/attachments"
    attachment_headers = {**headers, "X-Atlassian-Token": "no-check"}
    results = []
    for file_path in file_paths:
        with open(file_path, "rb") as f:
            resp = requests.post(
                url,
                headers=attachment_headers,
                auth=auth,
                files={"file": (os.path.basename(file_path), f)},
            )
        resp.raise_for_status()
        attachments = resp.json()
        print(f"Attached '{os.path.basename(file_path)}' to {ticket_id}")
        results.extend(attachments)
    return results

#This function creates a Jira Ticket
def create_ticket(project_key: str, summary: str, description: str = "", issue_type: str = "Task", priority: str | None = None, assignee_account_id: str | None = None, labels: list[str] | None = None, attachments: list[str] | None = None):
    url = f"{jira_base_url}/rest/api/3/issue"
    desc_body = None
    if description:
        desc_body = {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": description}],
                }
            ],
        }

    fields = {
        "project": {"key": project_key},
        "summary": summary,
        "issuetype": {"name": issue_type},
    }

    if desc_body:
        fields["description"] = desc_body
    if priority:
        fields["priority"] = {"name": priority}
    if assignee_account_id:
        fields["assignee"] = {"accountId": assignee_account_id}
    if labels:
        fields["labels"] = labels

    payload = {"fields": fields}

    resp = _do_request(
        "POST", url,
        headers={**headers, "Content-Type": "application/json"},
        auth=auth,
        json=payload,
    )
    result = resp.json()
    print(f"Created ticket: {result['key']} (id: {result['id']})")
    if attachments:
        add_attachment(result["key"], attachments)
    return result

#This function gets ticket details for the passed Jira
def get_ticket(ticket_id: str):
    url = f"{jira_base_url}/rest/api/3/issue/{ticket_id}"
    resp = _do_request("GET", url, headers=headers, auth=auth)
    return resp.json()
    
#This function prints ticket details in a readable format
def print_ticket_details(issue: dict):
    f = issue.get("fields", {})
    assignee = f.get("assignee") or {}
    print(f"""
ID:          {issue['key']}
Summary:     {f.get('summary', 'N/A')}
Status:      {f.get('status', {}).get('name', 'N/A')}
Priority:    {(f.get('priority') or {}).get('name', 'N/A')}
Assignee:    {(f.get('assignee') or {}).get('displayName', 'Unassigned')}
Created:     {f.get('created', 'N/A')}
Updated:     {f.get('updated', 'N/A')}
Description: {extract_text(f.get('description'))}
""")

#This function adds a comment in the passed Jira Ticket
def add_comment(ticket_id: str, text: str, attachments: list[str] | None = None):
    url = f"{jira_base_url}/rest/api/3/issue/{ticket_id}/comment"
    payload = {
        "body": {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": text}
                    ]
                }
            ]
        }
    }
    resp = _do_request("POST", url, headers={**headers, "Content-Type": "application/json"}, auth=auth, json=payload)
    if attachments:
        add_attachment(ticket_id, attachments)
    return resp.json()

#This function updates an existing Jira Ticket
def update_ticket(ticket_id: str, summary: str | None = None, description: str | None = None, issue_type: str | None = None, priority: str | None = None, assignee_account_id: str | None = None, labels: list[str] | None = None, attachments: list[str] | None = None):
    url = f"{jira_base_url}/rest/api/3/issue/{ticket_id}"
    fields = {}

    if summary is not None:
        fields["summary"] = summary
    if description is not None:
        fields["description"] = {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": description}],
                }
            ],
        }
    if issue_type is not None:
        fields["issuetype"] = {"name": issue_type}
    if priority is not None:
        fields["priority"] = {"name": priority}
    if assignee_account_id is not None:
        fields["assignee"] = {"accountId": assignee_account_id}
    if labels is not None:
        fields["labels"] = labels

    payload = {"fields": fields}

    resp = _do_request(
        "PUT", url,
        headers={**headers, "Content-Type": "application/json"},
        auth=auth,
        json=payload,
    )
    print(f"Updated ticket: {ticket_id}")
    if attachments:
        add_attachment(ticket_id, attachments)
    return ticket_id

#This function extracts text content from the JSON response
def extract_text(description: dict):
    if not description:
        return "N/A"
    texts = []
    if description.get("type") == "text":
        texts.append(description.get("text", ""))
    for node in description.get("content", []):
        texts.append(extract_text(node))
    return " ".join(t for t in texts if t).strip()

#This function gets comments from the passed Jira Ticket
def get_comments(ticket_id: str):
    url = f"{jira_base_url}/rest/api/3/issue/{ticket_id}/comment"
    resp = _do_request("GET", url, headers=headers, auth=auth)
    return resp.json().get("comments", [])

#This function prints comments in a readable format
def print_comments(comments: list[dict]):
    if not comments:
        print("No comments found.")
        return
    for c in comments:
        author = (c.get("author") or {}).get("displayName", "Unknown")
        created = c.get("created", "N/A")
        tz = (c.get("author") or {}).get("timeZone", "N/A")
        body = extract_text(c.get("body"))
        print(f"\n[{created} {tz}] {author}: {body}")
  
if __name__ == "__main__":

    parser = argparse.ArgumentParser(description="Jira Utility Script")
    parser.add_argument("ticket_id")
    args = parser.parse_args()

    ticket_id = args.ticket_id

    # Fetch and display current ticket details
    #issue = get_ticket(ticket_id)
    #print_ticket_details(issue)

    # --- create_ticket (commented out) ---
    # new_issue = create_ticket(
    #     project_key="SCRUM",
    #     summary="Automated ticket from Python script",
    #     description="This ticket was created programmatically via the Jira API",
    #     issue_type="Story",
    #     priority="Medium",
    #     labels=["automation"],
    #     attachments=["sample.png", "requirements.docx"],
    # )
    # created_issue = get_ticket(new_issue["key"])
    # print_ticket_details(created_issue)