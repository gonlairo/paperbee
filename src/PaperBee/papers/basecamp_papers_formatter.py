import time
import requests
import html
from typing import List, Optional, Tuple, Dict, Any
import pandas as pd
from logging import Logger

# Example: pip install requests


class BasecampPaperPublisher:
    """
    Publish papers (from a spreadsheet) to a Basecamp Message Board.

    Args:
        account_id: Basecamp account id (the {ACCOUNT_ID} in URLs).
        client_id, client_secret: OAuth credentials (from launchpad.37signals.com).
        access_token: optional initial access token.
        refresh_token: refresh token (used to obtain new access tokens).
        user_agent: string identifying your app (required by Basecamp).
        logger: logging.Logger instance.
    """

    LAUNCHPAD_TOKEN_URL = "https://launchpad.37signals.com/authorization/token"
    API_BASE = "https://3.basecampapi.com"

    def __init__(
        self,
        logger: Logger,
        account_id: str,
        client_id: str,
        client_secret: str,
        user_agent: str,
        bucket_id: str,
        board_id: str,
        access_token: str,
        refresh_token: str,
    ):
        self.account_id = account_id
        self.client_id = client_id
        self.client_secret = client_secret
        self.user_agent = user_agent
        self.logger = logger
        self.bucket_id = bucket_id
        self.board_id = board_id
        self.access_token = access_token
        self.refresh_token = refresh_token
        self._access_expires_at = 0  # epoch seconds when token expires (if known)

        # small session for connection pooling
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": user_agent,
            "Accept": "application/json"
        })

    # ----------------------------
    # Authentication helpers
    # ----------------------------
    def _ensure_access_token(self) -> None:
        """Ensure we have a valid access token; refresh if needed."""
        if not self.access_token or time.time() >= self._access_expires_at - 30:
            self.logger.debug("Refreshing Basecamp access token...")
            self._refresh_access_token()

    def _refresh_access_token(self) -> None:
        """Refresh access token using refresh_token."""
        if not self.refresh_token:
            raise RuntimeError(
                "No refresh_token available to refresh access token.")

        data = {
            "type": "refresh",  # community examples use this type for refresh
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": self.refresh_token,
        }
        resp = requests.post(self.LAUNCHPAD_TOKEN_URL,
                             data=data,
                             headers={"User-Agent": self.user_agent})
        if resp.status_code != 200:
            self.logger.error("Failed to refresh Basecamp token: %s %s",
                              resp.status_code, resp.text)
            resp.raise_for_status()
        payload = resp.json()
        self.access_token = payload.get("access_token")
        expires_in = payload.get("expires_in")
        if expires_in:
            self._access_expires_at = time.time() + int(expires_in)
        # if the server returned a new refresh_token, update it
        if payload.get("refresh_token"):
            self.refresh_token = payload["refresh_token"]

        # update session auth header
        self._session.headers.update({
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json; charset=utf-8"
        })

    # ----------------------------
    # Discovery helpers
    # ----------------------------
    # def list_projects(self) -> List[Dict[str, Any]]:
    #     """Return list of projects for the account."""
    #     self._ensure_access_token()
    #     url = f"{self.API_BASE}/{self.account_id}/projects.json"
    #     r = self._session.get(url)
    #     r.raise_for_status()
    #     return r.json()

    # def find_project_by_name(self,
    #                          project_name: str) -> Optional[Dict[str, Any]]:
    #     """Find the project dict by (case-insensitive) name. Returns the first match or None."""
    #     projects = self.list_projects()
    #     for p in projects:
    #         if p.get("name") and p["name"].lower() == project_name.lower():
    #             return p
    #     return None

    # def list_message_boards(self,
    #                         project_bucket_id: str) -> List[Dict[str, Any]]:
    #     """List message boards under a project's bucket id."""
    #     self._ensure_access_token()
    #     url = f"{self.API_BASE}/{self.account_id}/buckets/{project_bucket_id}/message_boards.json"
    #     r = self._session.get(url)
    #     r.raise_for_status()
    #     return r.json()

    # def find_message_board(self, project_bucket_id: str,
    #                        board_name: str) -> Optional[
    #                            Dict[str, Any],
    #                        ]:
    #     boards = self.list_message_boards(project_bucket_id)
    #     for b in boards:
    #         if b.get("name") and b["name"].lower() == board_name.lower():
    #             return b
    #     return None

    # ----------------------------
    # Formatting / content helpers
    # ----------------------------
    @staticmethod
    def _escape_html(text: str) -> str:
        return html.escape(text)

    def build_message(
        self,
        papers: List[List[str]],
    ) -> str:
        """
        Build a simple HTML body for a Basecamp Message's `content` field.
        Basecamp uses HTML rich text for message content.
        """
        parts = []
        parts.append(
            f"<p><strong>Good morning ☕ Here are today's papers!</strong></p>")
        parts.append("<h3>Papers</h3><ul>")

        for p in papers:
            title = p[4]
            link = p[-1]
            parts.append(
                f"<li><a href='{link}'>{self._escape_html(title)}</a></li>")
        parts.append("</ul>")
        parts.append("<hr/>")
        parts.append('<p>Posted automatically by <code>paperbee</code></p>')
        return "".join(parts)

        #example: ['10.1101/2025.09.10.674954', '2025-09-17', '2025-09-16', 'TRUE', 'Differentiation hierarchy in adult B cell acute lymphoblastic leukemia at clonal resolution', '', None, 'https://doi.org/10.1101/2025.09.10.674954']

    # ----------------------------
    # Publish
    # ----------------------------

    @staticmethod
    def format_papers(
        papers_list: List[List[str]],) -> Tuple[List[str], List[str]]:
        """
        Splits and formats papers into preprints and regular papers for Mattermost.
        Args:
            papers_list: List of paper records.
        Returns:
            Tuple of (papers, preprints) as formatted strings.
        """
        papers = []
        preprints = []
        for idx, paper in enumerate(papers_list):
            if not isinstance(paper, list) or len(paper) < 6:
                print(
                    f"Warning: Skipping invalid paper at index {idx}: {paper}")
                continue
            emoji = "✏️" if paper[3] == "TRUE" else "🗞️"
            title = paper[4]
            link = paper[-1]
            if not isinstance(title, str) or not isinstance(link, str):
                print(
                    f"Warning: Skipping paper with invalid title or link at index {idx}: {paper}"
                )
                continue
            formatted_paper = f"{emoji} [{title}]({link})"
            if paper[3] == "TRUE":
                preprints.append(formatted_paper)
            else:
                papers.append(formatted_paper)
        return papers, preprints

    async def publish_papers(self,
                             papers_list: List[List[str]]) -> Dict[str, Any]:
        """  
        Find project + board, and create a Message.
        Returns the created message JSON on success.
        """
        self._ensure_access_token()

        # # find project -> get its bucket id
        # project = self.find_project_by_name(project_name)
        # if not project:
        #     raise RuntimeError(
        #         f"Project named '{project_name}' not found in account {self.account_id}."
        #     )

        # # NOTE: in many Basecamp examples the project's "id" is its bucket id; some responses include 'id' or 'bucket' keys.
        # # We'll try to use project['id'] as the bucket id.
        # bucket_id = str(
        #     project.get("id") or project.get("bucket", {}).get("id"))
        # if not bucket_id:
        #     raise RuntimeError(
        #         "Could not determine project bucket id from project metadata.")

        # board = self.find_message_board(bucket_id, board_name)
        # if not board:
        #     raise RuntimeError(
        #         f"Message board '{board_name}' not found under project '{project_name}'."
        #     )

        # board_id = str(board["id"])

        # if not subject:
        #     subject = f"Papers — {today or ''}".strip()

        #papers, preprints = self.format_papers(papers_list)
        content_html = self.build_message(papers_list)

        body = {
            "subject": "Hello world!",
            "content": content_html,
            "status": "active"
        }

        url = f"{self.API_BASE}/{self.account_id}/buckets/{self.bucket_id}/message_boards/{self.board_id}/messages.json"
        #self.session already has the headers, I think we don't need to pass them again
        r = self._session.post(url, json=body)
        if r.status_code not in (200, 201):
            self.logger.error("Failed to create message: %s %s", r.status_code,
                              r.text)
            r.raise_for_status()
            self.logger.info("Posted message to Basecamp board")
        return r.json()
        #return body
