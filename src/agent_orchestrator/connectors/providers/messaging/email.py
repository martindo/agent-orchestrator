"""Email messaging connector provider.

Implements send_message, notify_user, and create_thread via SMTP (stdlib).
Uses STARTTLS by default (port 587). The smtplib calls are wrapped in
asyncio.get_running_loop().run_in_executor() for async compatibility.
"""
from __future__ import annotations

import asyncio
import logging
import smtplib
import ssl
import uuid
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from ...models import ConnectorCostInfo
from ._base import BaseMessagingProvider, MessagingProviderError

logger = logging.getLogger(__name__)

_DEFAULT_AGENT_SUBJECT = "Message from Agent Orchestrator"
_DEFAULT_NOTIFY_SUBJECT = "Notification from Agent Orchestrator"


class EmailMessagingProvider(BaseMessagingProvider):
    """SMTP email messaging connector provider.

    Sends emails via SMTP with STARTTLS (port 587 by default). The
    notify_user operation treats user_id as the recipient email address.

    Example::

        provider = EmailMessagingProvider(
            smtp_host="smtp.gmail.com",
            username="agent@example.com",
            password="app-password",
            from_address="agent@example.com",
        )
    """

    def __init__(
        self,
        smtp_host: str,
        username: str,
        password: str,
        from_address: str,
        smtp_port: int = 587,
        use_tls: bool = True,
    ) -> None:
        if not smtp_host:
            raise ValueError("EmailMessagingProvider requires a non-empty smtp_host")
        if not username:
            raise ValueError("EmailMessagingProvider requires a non-empty username")
        if not password:
            raise ValueError("EmailMessagingProvider requires a non-empty password")
        if not from_address:
            raise ValueError("EmailMessagingProvider requires a non-empty from_address")
        self._smtp_host = smtp_host
        self._smtp_port = smtp_port
        self._username = username
        self._password = password
        self._from_address = from_address
        self._use_tls = use_tls
        self._api_token = username  # satisfies is_available() check

    @classmethod
    def from_env(cls) -> "EmailMessagingProvider | None":
        """Create an instance from environment variables.

        Required env vars: ``SMTP_HOST``, ``SMTP_USERNAME``, ``SMTP_PASSWORD``,
        ``SMTP_FROM_ADDRESS``
        Optional env vars: ``SMTP_PORT`` (default: 587), ``SMTP_USE_TLS`` (default: true)

        Returns None if any required env var is missing.
        """
        import os
        smtp_host = os.environ.get("SMTP_HOST", "")
        username = os.environ.get("SMTP_USERNAME", "")
        password = os.environ.get("SMTP_PASSWORD", "")
        from_address = os.environ.get("SMTP_FROM_ADDRESS", "")
        if not smtp_host or not username or not password or not from_address:
            return None
        port_str = os.environ.get("SMTP_PORT", "587")
        tls_str = os.environ.get("SMTP_USE_TLS", "true").lower()
        return cls(
            smtp_host=smtp_host,
            username=username,
            password=password,
            from_address=from_address,
            smtp_port=int(port_str),
            use_tls=tls_str not in ("false", "0", "no"),
        )

    @property
    def provider_id(self) -> str:
        """Unique provider identifier used for registry lookups."""
        return "messaging.email"

    @property
    def display_name(self) -> str:
        """Human-readable name shown in the registry descriptor."""
        return "Email Messaging (SMTP)"

    def _send_email_sync(self, to: str, subject: str, body: str) -> str:
        """Send an email synchronously via SMTP.

        Args:
            to: Recipient email address.
            subject: Email subject line.
            body: Email body text (plain text).

        Returns:
            The Message-ID header value for the sent email.

        Raises:
            MessagingProviderError: When the SMTP operation fails.
        """
        message_id = f"<{uuid.uuid4()}@agent-orchestrator>"

        msg = MIMEMultipart("alternative")
        msg["From"] = self._from_address
        msg["To"] = to
        msg["Subject"] = subject
        msg["Message-ID"] = message_id
        msg.attach(MIMEText(body, "plain"))

        try:
            with smtplib.SMTP(self._smtp_host, self._smtp_port) as smtp:
                smtp.ehlo()
                if self._use_tls:
                    smtp.starttls(context=ssl.create_default_context())
                smtp.login(self._username, self._password)
                smtp.sendmail(self._from_address, to, msg.as_string())
        except smtplib.SMTPException as exc:
            raise MessagingProviderError(f"SMTP error: {exc}") from exc

        logger.info(
            "Email sent: smtp_host=%r from=%r to=%r subject=%r message_id=%r",
            self._smtp_host,
            self._from_address,
            to,
            subject,
            message_id,
        )

        return message_id

    async def _send_message(
        self,
        destination: str,
        content: str,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """Send an email message to the destination address.

        Args:
            destination: Recipient email address.
            content: Email body text.

        Returns:
            Tuple of (ExternalArtifact dict, None — no API cost).

        Raises:
            MessagingProviderError: When the SMTP operation fails.
        """
        subject = _DEFAULT_AGENT_SUBJECT
        message_id = await asyncio.get_running_loop().run_in_executor(
            None, self._send_email_sync, destination, subject, content
        )

        artifact = self._make_message_artifact(
            provider=self.provider_id,
            connector_id=self.provider_id,
            message_id=message_id,
            channel=destination,
            sender=self._from_address,
            recipients=[destination],
            subject=None,
            body=content,
            raw_payload={"to": destination, "subject": subject},
            resource_type="message",
            provenance={"provider": "email", "smtp_host": self._smtp_host},
        )

        return artifact.model_dump(mode="json"), None

    async def _notify_user(
        self,
        user_id: str,
        content: str,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """Send a notification email to the user's email address.

        The user_id is treated as the recipient email address.

        Args:
            user_id: Recipient email address.
            content: Notification body text.

        Returns:
            Tuple of (ExternalArtifact dict, None — no API cost).

        Raises:
            MessagingProviderError: When the SMTP operation fails.
        """
        subject = _DEFAULT_NOTIFY_SUBJECT
        message_id = await asyncio.get_running_loop().run_in_executor(
            None, self._send_email_sync, user_id, subject, content
        )

        artifact = self._make_message_artifact(
            provider=self.provider_id,
            connector_id=self.provider_id,
            message_id=message_id,
            channel=user_id,
            sender=self._from_address,
            recipients=[user_id],
            subject=None,
            body=content,
            raw_payload={"to": user_id, "subject": subject},
            resource_type="notification",
            provenance={"provider": "email", "smtp_host": self._smtp_host},
        )

        return artifact.model_dump(mode="json"), None

    async def _create_thread(
        self,
        destination: str,
        title: str,
        content: str,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """Send a thread-initiating email with the title as subject.

        Args:
            destination: Recipient email address.
            title: Email subject line (thread title).
            content: Email body text.

        Returns:
            Tuple of (ExternalArtifact dict, None — no API cost).

        Raises:
            MessagingProviderError: When the SMTP operation fails.
        """
        message_id = await asyncio.get_running_loop().run_in_executor(
            None, self._send_email_sync, destination, title, content
        )

        artifact = self._make_message_artifact(
            provider=self.provider_id,
            connector_id=self.provider_id,
            message_id=message_id,
            channel=destination,
            sender=self._from_address,
            recipients=[destination],
            subject=title,
            body=content,
            raw_payload={"to": destination, "subject": title},
            resource_type="thread",
            provenance={"provider": "email", "smtp_host": self._smtp_host},
        )

        return artifact.model_dump(mode="json"), None
