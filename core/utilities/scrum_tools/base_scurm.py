import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class ScrumTool:
    """
    Pass platform="jira" (or any supported backend) and call operations normally.

    Usage:
        tool = ScrumTool("jira")
        tool.create_ticket(project_key="SCRUM", summary="Fix bug")
        tool.update_ticket("SCRUM-5", priority="High")
        tool.add_comment("SCRUM-5", "Work started", attachments=["log.txt"])
    """

    def __init__(self, platform: str):
        if platform.lower() == "jira":
            import jira_utility
            self._backend = jira_utility
        else:
            raise ValueError(f"Unsupported platform: '{platform}'. Supported: ['jira']")

    def create_ticket(self, project_key, summary, description="", issue_type="Task",
                      priority=None, assignee_account_id=None, labels=None, attachments=None):
        return self._backend.create_ticket(
            project_key=project_key, summary=summary, description=description,
            issue_type=issue_type, priority=priority,
            assignee_account_id=assignee_account_id, labels=labels, attachments=attachments,
        )

    def get_ticket(self, ticket_id):
        return self._backend.get_ticket(ticket_id)

    def update_ticket(self, ticket_id, summary=None, description=None, issue_type=None,
                      priority=None, assignee_account_id=None, labels=None, attachments=None):
        return self._backend.update_ticket(
            ticket_id=ticket_id, summary=summary, description=description,
            issue_type=issue_type, priority=priority,
            assignee_account_id=assignee_account_id, labels=labels, attachments=attachments,
        )

    def add_comment(self, ticket_id, text, attachments=None):
        return self._backend.add_comment(ticket_id=ticket_id, text=text, attachments=attachments)

    def get_comments(self, ticket_id):
        return self._backend.get_comments(ticket_id)

    def add_attachment(self, ticket_id, file_paths):
        return self._backend.add_attachment(ticket_id=ticket_id, file_paths=file_paths)

    def print_ticket_details(self, issue):
        return self._backend.print_ticket_details(issue)

    def print_comments(self, comments):
        return self._backend.print_comments(comments)
