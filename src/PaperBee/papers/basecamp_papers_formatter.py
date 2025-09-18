import html
import time
from datetime import datetime
from logging import Logger
from typing import Any, Dict, List

import requests


class BasecampPaperPublisher:
    """
    Publish papers (from a spreadsheet) to a Basecamp Message Board.

    Args:
        logger: logging.Logger instance.
        account_id: Basecamp account id (the {ACCOUNT_ID} in URLs).
        client_id, client_secret: OAuth credentials (from launchpad.37signals.com).
        client_secret: OAuth credentials (from launchpad.37signals.com).
        user_agent: string identifying your app (required by Basecamp).
        bucket_id: Basecamp bucket id (the {BUCKET_ID} in URLs).
        board_id: Basecamp board id (the {BOARD_ID} in URLs).
        access_token: optional initial access token.
        refresh_token: refresh token (used to obtain new access tokens).
    """

    LAUNCHPAD_AUTH_URL = "https://launchpad.37signals.com/authorization/token"
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
        self._session.headers.update({"User-Agent": user_agent, "Accept": "application/json"})

    def _ensure_access_token(self) -> None:
        """Ensure we have a valid access token; refresh if needed."""
        if not self.access_token or time.time() >= self._access_expires_at - 30:
            self.logger.debug("Refreshing Basecamp access token...")
            self._refresh_access_token()

    def _refresh_access_token(self) -> None:
        """Refresh access token using refresh_token."""
        if not self.refresh_token:
            msg = "No refresh_token available."
            raise RuntimeError(msg)

        # NOTE(Rodrigo): {"type": "refresh"} as in https://github.com/basecamp/api/blob/master/sections/authentication.md
        data = {
            "type": "refresh",  # community examples use this type for refresh
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": self.refresh_token,
        }
        resp = requests.post(self.LAUNCHPAD_AUTH_URL, data=data, headers={"User-Agent": self.user_agent}, timeout=30)
        if resp.status_code != 200:
            self.logger.error("Failed to refresh Basecamp token: %s %s", resp.status_code, resp.text)
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
            "Content-Type": "application/json; charset=utf-8",
        })

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
        parts.append("<p><strong>Good morning ☕ Here are today's papers!</strong></p>")
        # parts.append("<h3>Papers</h3><ul>")
        parts.append("<ul>")
        for p in papers:
            title = p[4]
            link = p[-1]
            parts.append(f"<li><a href='{link}'>{self._escape_html(title)}</a></li>")
        parts.append("</ul>")
        # parts.append("<hr/>")
        # parts.append("<p>Posted automatically by <code>paperbee</code></p>")
        return "".join(parts)

        # example: ['10.1101/2025.09.10.674954', '2025-09-17', '2025-09-16', 'TRUE', 'Differentiation hierarchy in adult B cell acute lymphoblastic leukemia at clonal resolution', '', None, 'https://doi.org/10.1101/2025.09.10.674954']

    async def publish_papers(self, papers_list: List[List[str]]) -> Dict[str, Any]:
        self._ensure_access_token()

        # papers, preprints = self.format_papers(papers_list)
        content_html = self.build_message(papers_list)

        today_str = datetime.now().strftime("%d-%m-%Y")
        body = {"subject": f"Papers from {today_str}", "content": content_html, "status": "active"}

        url = f"{self.API_BASE}/{self.account_id}/buckets/{self.bucket_id}/message_boards/{self.board_id}/messages.json"
        # self.session already has the headers, I think we don't need to pass them again
        r = self._session.post(url, json=body)
        if r.status_code not in (200, 201):
            self.logger.error("Failed to create message: %s %s", r.status_code, r.text)
            r.raise_for_status()
            self.logger.info("Posted message to Basecamp board")
        return r.json()
