"""ReviewQueue — Persistent queue of items flagged for human review.

Items continue processing (non-blocking) but are queued for later review.

Thread-safe: All public methods use internal lock.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
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


class ReviewQueue:
    """Persistent queue for items requiring human review.

    Non-blocking: Items are queued AFTER the governance decision.
    Processing continues regardless of review status.

    Thread-safe: All public methods use internal lock.
    """

    def __init__(self) -> None:
        self._items: dict[str, ReviewItem] = {}
        self._counter = 0
        self._lock = threading.Lock()

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
            self._items[review_id] = item
            logger.info("Queued for review: %s (work=%s)", review_id, work_id)
            return review_id

    def complete_review(
        self,
        review_id: str,
        reviewed_by: str,
        notes: str = "",
    ) -> bool:
        """Mark a review item as reviewed.

        Args:
            review_id: Review item ID.
            reviewed_by: Reviewer identifier.
            notes: Review notes.

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
            logger.info("Review completed: %s by %s", review_id, reviewed_by)
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

    def pending_count(self) -> int:
        """Count of pending reviews."""
        with self._lock:
            return sum(1 for i in self._items.values() if not i.reviewed)
