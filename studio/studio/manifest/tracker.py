"""Generation manifest tracker — prevents overwriting user-edited files.

Maintains a ``.studio-manifest.json`` file in each profile directory that
records which files were generated, when, and who owns them.

Ownership model:
- ``studio`` — Studio-generated declarative YAML.  Safe to regenerate.
- ``user``   — Extension stubs that were generated once, then edited by
  the user.  Studio must NOT overwrite these unless ``force=True``.

On regeneration, the tracker checks the manifest and:
- Overwrites ``studio``-owned files freely.
- Skips ``user``-owned files (or writes to ``.studio-pending/`` for merge).
- Flags conflicts for files whose on-disk hash doesn't match the manifest.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from studio.exceptions import ManifestError

logger = logging.getLogger(__name__)

MANIFEST_FILENAME = ".studio-manifest.json"


class FileOwnership(str, Enum):
    """Who owns a generated file."""

    STUDIO = "studio"
    USER = "user"


@dataclass
class ManifestEntry:
    """Record for a single generated file.

    Attributes:
        file_path: Relative path within the profile directory.
        generated_at: ISO timestamp of last generation.
        content_hash: SHA-256 hash of the generated content.
        ownership: Who owns this file.
        overwrite_policy: 'always', 'never', or 'ask'.
    """

    file_path: str
    generated_at: str
    content_hash: str
    ownership: FileOwnership
    overwrite_policy: str = "always"


@dataclass
class Manifest:
    """Complete generation manifest for a profile directory.

    Attributes:
        version: Manifest schema version.
        profile_name: Name of the profile.
        entries: File entries keyed by relative path.
        last_generated: ISO timestamp of the last generation run.
    """

    version: str = "1.0"
    profile_name: str = ""
    entries: dict[str, ManifestEntry] = field(default_factory=dict)
    last_generated: str = ""


def _hash_content(content: bytes) -> str:
    """Compute SHA-256 hash of file content."""
    return hashlib.sha256(content).hexdigest()


def _hash_file(path: Path) -> str:
    """Compute SHA-256 hash of a file on disk."""
    try:
        return _hash_content(path.read_bytes())
    except OSError:
        return ""


class ManifestTracker:
    """Tracks generated files and ownership for a profile directory.

    Args:
        profile_dir: The profile directory to manage.
    """

    def __init__(self, profile_dir: Path) -> None:
        self._profile_dir = profile_dir
        self._manifest_path = profile_dir / MANIFEST_FILENAME
        self._manifest: Manifest | None = None

    def _load(self) -> Manifest:
        """Load the manifest from disk, or return an empty one."""
        if self._manifest is not None:
            return self._manifest

        if not self._manifest_path.exists():
            self._manifest = Manifest()
            return self._manifest

        try:
            data = json.loads(self._manifest_path.read_text(encoding="utf-8"))
            entries: dict[str, ManifestEntry] = {}
            for key, entry_data in data.get("entries", {}).items():
                entries[key] = ManifestEntry(
                    file_path=entry_data["file_path"],
                    generated_at=entry_data["generated_at"],
                    content_hash=entry_data["content_hash"],
                    ownership=FileOwnership(entry_data.get("ownership", "studio")),
                    overwrite_policy=entry_data.get("overwrite_policy", "always"),
                )
            self._manifest = Manifest(
                version=data.get("version", "1.0"),
                profile_name=data.get("profile_name", ""),
                entries=entries,
                last_generated=data.get("last_generated", ""),
            )
            return self._manifest
        except (json.JSONDecodeError, KeyError, OSError) as exc:
            logger.warning("Failed to load manifest, starting fresh: %s", exc)
            self._manifest = Manifest()
            return self._manifest

    def _save(self) -> None:
        """Persist the manifest to disk."""
        manifest = self._load()
        self._profile_dir.mkdir(parents=True, exist_ok=True)

        data: dict[str, Any] = {
            "version": manifest.version,
            "profile_name": manifest.profile_name,
            "last_generated": manifest.last_generated,
            "entries": {
                key: {
                    "file_path": entry.file_path,
                    "generated_at": entry.generated_at,
                    "content_hash": entry.content_hash,
                    "ownership": entry.ownership.value,
                    "overwrite_policy": entry.overwrite_policy,
                }
                for key, entry in manifest.entries.items()
            },
        }

        try:
            self._manifest_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            logger.debug("Saved manifest to %s", self._manifest_path)
        except OSError as exc:
            raise ManifestError(f"Failed to save manifest: {exc}") from exc

    def check_conflicts(self) -> list[str]:
        """Check for files that would be overwritten and are user-owned.

        Returns:
            List of conflict descriptions. Empty means safe to proceed.
        """
        manifest = self._load()
        conflicts: list[str] = []

        for key, entry in manifest.entries.items():
            if entry.ownership != FileOwnership.USER:
                continue

            file_path = self._profile_dir / entry.file_path
            if not file_path.exists():
                continue

            current_hash = _hash_file(file_path)
            if current_hash != entry.content_hash:
                conflicts.append(
                    f"User-owned file '{entry.file_path}' has been modified since "
                    f"last generation. Use force=True to overwrite."
                )

        return conflicts

    def update_manifest(
        self,
        files: list[Path],
        ownership: str = "studio",
    ) -> None:
        """Update the manifest after generating files.

        Args:
            files: List of absolute paths to generated files.
            ownership: Default ownership for new entries ('studio' or 'user').
        """
        manifest = self._load()
        now = datetime.now(timezone.utc).isoformat()
        manifest.last_generated = now

        file_ownership = FileOwnership(ownership)

        for file_path in files:
            try:
                relative = file_path.relative_to(self._profile_dir)
            except ValueError:
                relative = Path(file_path.name)

            key = str(relative)
            existing = manifest.entries.get(key)

            # Don't downgrade user-owned files back to studio
            entry_ownership = file_ownership
            overwrite_policy = "always"
            if existing and existing.ownership == FileOwnership.USER:
                entry_ownership = FileOwnership.USER
                overwrite_policy = "never"

            manifest.entries[key] = ManifestEntry(
                file_path=key,
                generated_at=now,
                content_hash=_hash_file(file_path),
                ownership=entry_ownership,
                overwrite_policy=overwrite_policy,
            )

        manifest.profile_name = self._profile_dir.name
        self._save()

    def mark_user_owned(self, relative_path: str) -> None:
        """Mark a file as user-owned so it won't be overwritten.

        Args:
            relative_path: Path relative to the profile directory.
        """
        manifest = self._load()
        entry = manifest.entries.get(relative_path)
        if entry is None:
            file_path = self._profile_dir / relative_path
            manifest.entries[relative_path] = ManifestEntry(
                file_path=relative_path,
                generated_at=datetime.now(timezone.utc).isoformat(),
                content_hash=_hash_file(file_path),
                ownership=FileOwnership.USER,
                overwrite_policy="never",
            )
        else:
            manifest.entries[relative_path] = ManifestEntry(
                file_path=entry.file_path,
                generated_at=entry.generated_at,
                content_hash=entry.content_hash,
                ownership=FileOwnership.USER,
                overwrite_policy="never",
            )
        self._save()

    def get_manifest(self) -> Manifest:
        """Return the current manifest state."""
        return self._load()
