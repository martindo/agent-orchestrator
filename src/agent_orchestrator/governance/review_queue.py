"""ReviewQueue — Persistent queue of items flagged for human review.

Items continue processing (non-blocking) but are queued for later review.

Thread-safe: All public methods use internal lock.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ReviewItem:
    """An item queued for human review."""

    id: str
    work_id: str
    phase_id: str
    reason: str
    context: dict[str, Any] = field(default_factory=dict)
    decision_data: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    reviewed: bool = False
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    review_notes: str = ""
    decision: str = ""  # "", "approved", "rejected"
    review_deadline: datetime | None = None


class ReviewQueue:
    """Persistent queue for items requiring human review.

    Non-blocking: Items are queued AFTER the governance decision.
    Processing continues regardless of review status.

    Thread-safe: All public methods use internal lock.
    """

    def __init__(
        self,
        persistence_path: Path | None = None,
        review_sla_seconds: float = 0,
    ) -> None:
        self._items: dict[str, ReviewItem] = {}
        self._counter = 0
        self._lock = threading.Lock()
        self._persistence_path = persistence_path
        self._review_sla_seconds = review_sla_seconds

        if self._persistence_path is not None and self._persistence_path.exists():
            self._load_from_disk()

    def enqueue(
        self,
        work_id: str,
        phase_id: str,
        reason: str,
        context: dict[str, Any] | None = None,
        decision_data: dict[str, Any] | None = None,
    ) -> str:
        """Add an item to the review queue.

        Args:
            work_id: Work item ID.
            phase_id: Phase where review was triggered.
            reason: Why the item needs review.
            context: Evaluation context.
            decision_data: Governance decision details.

        Returns:
            Review item ID.
        """
        with self._lock:
            self._counter += 1
            review_id = f"review-{self._counter}"
            item = ReviewItem(
                id=review_id,
                work_id=work_id,
                phase_id=phase_id,
                reason=reason,
                context=context or {},
                decision_data=decision_data or {},
            )
            if self._review_sla_seconds > 0:
                item.review_deadline = item.created_at + timedelta(seconds=self._review_sla_seconds)
            self._items[review_id] = item
            self._persist_item(item)
            logger.info("Queued for review: %s (work=%s)", review_id, work_id)
            return review_id

    def complete_review(
        self,
        review_id: str,
        reviewed_by: str,
        notes: str = "",
        decision: str = "approved",
    ) -> bool:
        """Mark a review item as reviewed.

        Args:
            review_id: Review item ID.
            reviewed_by: Reviewer identifier.
            notes: Review notes.
            decision: Review decision ("approved" or "rejected").

        Returns:
            True if item was found and marked.
        """
        with self._lock:
            item = self._items.get(review_id)
            if item is None:
                return False
            item.reviewed = True
            item.reviewed_by = reviewed_by
            item.reviewed_at = datetime.now(timezone.utc)
            item.review_notes = notes
            item.decision = decision
            self._persist_item(item)
            logger.info("Review completed: %s by %s (decision=%s)", review_id, reviewed_by, decision)
            return True

    def get_pending(self) -> list[ReviewItem]:
        """Get all pending (unreviewed) items."""
        with self._lock:
            return [i for i in self._items.values() if not i.reviewed]

    def get_all(self) -> list[ReviewItem]:
        """Get all review items."""
        with self._lock:
            return list(self._items.values())

    def get_item(self, review_id: str) -> ReviewItem | None:
        """Get a specific review item."""
        with self._lock:
            return self._items.get(review_id)

    def get_completed(self) -> list[ReviewItem]:
        """Get all completed (reviewed) items."""
        with self._lock:
            return [i for i in self._items.values() if i.reviewed]

    def pending_count(self) -> int:
        """Count of pending reviews."""
        with self._lock:
            return sum(1 for i in self._items.values() if not i.reviewed)

    def get_overdue(self) -> list[ReviewItem]:
        """Get review items that have exceeded their SLA deadline."""
        now = datetime.now(timezone.utc)
        with self._lock:
            return [
                i for i in self._items.values()
                if i.review_deadline is not None and now > i.review_deadline and not i.reviewed
            ]

    def _persist_item(self, item: ReviewItem) -> None:
        """Append an item as a JSON line to the persistence file."""
        if self._persistence_path is None:
            return
        try:
            self._persistence_path.parent.mkdir(parents=True, exist_ok=True)
            data = asdict(item)
            data["created_at"] = item.created_at.isoformat()
            if item.reviewed_at is not None:
                data["reviewed_at"] = item.reviewed_at.isoformat()
            if item.review_deadline is not None:
                data["review_deadline"] = item.review_deadline.isoformat()
            with open(self._persistence_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(data) + "\n")
        except OSError as e:
            logger.warning("Failed to persist review item %s: %s", item.id, e)

    def _load_from_disk(self) -> None:
        """Load review items from the JSONL persistence file."""
        if self._persistence_path is None or not self._persistence_path.exists():
            return
        try:
            with open(self._persistence_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    data = json.loads(line)
                    data["created_at"] = datetime.fromisoformat(data["created_at"])
                    if data.get("reviewed_at"):
                        data["reviewed_at"] = datetime.fromisoformat(data["reviewed_at"])
                    else:
                        data["reviewed_at"] = None
                    if data.get("review_deadline"):
                        data["review_deadline"] = datetime.fromisoformat(data["review_deadline"])
                    else:
                        data["review_deadline"] = None
                    item = ReviewItem(**data)
                    self._items[item.id] = item
                    # Update counter from loaded IDs
                    try:
                        num = int(item.id.split("-", 1)[1])
                        if num > self._counter:
                            self._counter = num
                    except (IndexError, ValueError):
                        pass
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load review queue from disk: %s", e)
