"""Settings store — YAML-based configuration persistence with atomic writes.

Uses temp file + rename pattern for corruption protection.
Supports API key storage with environment variable fallback.

Thread-safe: All public methods use internal lock.

Reuses pattern from coderswarm-v2/ui/settings.py.
"""

from __future__ import annotations

import logging
import os
import random
import shutil
import threading
from pathlib import Path
from typing import Any

import yaml

from agent_orchestrator.exceptions import PersistenceError

logger = logging.getLogger(__name__)

MAX_WRITE_RETRIES = 3
RETRY_BASE_DELAY_SECONDS = 0.1


def _atomic_write_yaml(path: Path, data: dict[str, Any]) -> None:
    """Write YAML data atomically with temp file + rename.

    Creates a backup before overwriting. Retries on Windows file locking.

    Args:
        path: Target file path.
        data: Data to serialize as YAML.

    Raises:
        PersistenceError: If all write attempts fail.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    for attempt in range(1, MAX_WRITE_RETRIES + 1):
        temp_path = path.with_suffix(
            f".yaml.tmp.{os.getpid()}.{random.randint(1000, 9999)}",
        )
        try:
            # Write to temp file
            with open(temp_path, "w", encoding="utf-8") as f:
                yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

            # Verify written data
            with open(temp_path, "r", encoding="utf-8") as f:
                verify = yaml.safe_load(f)

            if not isinstance(verify, dict):
                msg = f"Verification failed: expected dict, got {type(verify)}"
                raise PersistenceError(msg)

            # Create backup if target exists
            if path.exists():
                backup_path = path.with_suffix(".yaml.bak")
                shutil.copy2(str(path), str(backup_path))

            # Atomic replace
            if os.name == "nt" and path.exists():
                os.remove(path)
            shutil.move(str(temp_path), str(path))
            return

        except OSError as e:
            logger.warning(
                "Write attempt %d/%d failed for %s: %s",
                attempt, MAX_WRITE_RETRIES, path, e,
            )
            if attempt == MAX_WRITE_RETRIES:
                msg = f"Failed to write {path} after {MAX_WRITE_RETRIES} attempts: {e}"
                raise PersistenceError(msg) from e
            import time
            time.sleep(RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1)))
        finally:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass


def _read_yaml(path: Path) -> dict[str, Any]:
    """Read a YAML file, returning empty dict if missing.

    Args:
        path: File to read.

    Returns:
        Parsed YAML data.

    Raises:
        PersistenceError: If file exists but cannot be parsed.
    """
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data if isinstance(data, dict) else {}
    except yaml.YAMLError as e:
        msg = f"Failed to parse {path}: {e}"
        raise PersistenceError(msg) from e


class SettingsStore:
    """Persistent settings store with atomic writes and env var fallback.

    Thread-safe: All public methods use internal lock.

    State Ownership: SettingsStore owns the settings file on disk.
    """

    def __init__(self, settings_path: Path) -> None:
        self._path = settings_path
        self._lock = threading.Lock()

    def load(self) -> dict[str, Any]:
        """Load settings from disk.

        Returns:
            Settings dict.
        """
        with self._lock:
            data = _read_yaml(self._path)
            # Apply env var fallbacks for API keys
            api_keys = data.get("api_keys", {})
            for provider in list(api_keys.keys()):
                env_key = f"AGENT_ORCH_{provider.upper()}_API_KEY"
                env_val = os.environ.get(env_key)
                if env_val and not api_keys[provider]:
                    api_keys[provider] = env_val
            data["api_keys"] = api_keys
            return data

    def save(self, data: dict[str, Any]) -> None:
        """Save settings to disk atomically.

        API keys that match env vars are not persisted (security).

        Args:
            data: Settings dict to persist.
        """
        with self._lock:
            # Strip API keys that come from env vars
            safe_data = dict(data)
            api_keys = dict(safe_data.get("api_keys", {}))
            for provider, key in list(api_keys.items()):
                env_key = f"AGENT_ORCH_{provider.upper()}_API_KEY"
                if os.environ.get(env_key) == key:
                    api_keys[provider] = ""  # Don't persist env-sourced keys
            safe_data["api_keys"] = api_keys

            _atomic_write_yaml(self._path, safe_data)
            logger.info("Settings saved to %s", self._path)

    def get(self, key: str, default: Any = None) -> Any:
        """Get a single setting value."""
        data = self.load()
        return data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Set a single setting value."""
        data = self.load()
        data[key] = value
        self.save(data)
