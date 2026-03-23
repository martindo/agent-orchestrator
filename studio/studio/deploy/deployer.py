"""Deploy generated profiles to the runtime workspace.

Deployment writes YAML files to ``{workspace}/profiles/{profile_name}/``
and optionally triggers a reload on the running runtime instance.

Two deployment paths:
1. **File-based** — write YAML to the profiles directory (always available).
2. **API-triggered reload** — POST to the runtime's config endpoint to
   trigger a hot-reload (only when runtime is running).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from studio.config import StudioConfig
from studio.exceptions import DeploymentError
from studio.generation.generator import write_profile_to_directory
from studio.ir.models import TeamSpec
from studio.manifest.tracker import ManifestTracker
from studio.validation.validator import validate_team

logger = logging.getLogger(__name__)

CONFIG_RELOAD_ENDPOINT = "/api/v1/config/reload"
SWITCH_PROFILE_ENDPOINT = "/api/v1/config/profile"
RELOAD_TIMEOUT_SECONDS = 10.0


@dataclass
class DeployResult:
    """Result of a profile deployment.

    Attributes:
        success: Whether the deployment was successful.
        profile_dir: Path to the deployed profile directory.
        files_written: List of files written to disk.
        runtime_reloaded: Whether the runtime was triggered to reload.
        errors: Any errors that occurred.
        warnings: Non-blocking issues.
    """

    success: bool
    profile_dir: Path
    files_written: list[Path] = field(default_factory=list)
    runtime_reloaded: bool = False
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _slugify(name: str) -> str:
    """Convert a team name into a directory-safe slug."""
    slug = name.lower().strip()
    slug = slug.replace(" ", "-")
    # Remove anything that isn't alphanumeric or hyphen
    slug = "".join(c for c in slug if c.isalnum() or c == "-")
    # Collapse multiple hyphens
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-") or "unnamed-profile"


def _trigger_reload(config: StudioConfig, profile_name: str) -> bool:
    """Attempt to trigger a config reload on the running runtime.

    Returns True if reload was successful, False if runtime is unreachable.
    """
    url = f"{config.runtime_api_url}{SWITCH_PROFILE_ENDPOINT}"
    logger.info("Triggering profile switch to '%s' at %s", profile_name, url)

    try:
        with httpx.Client(timeout=RELOAD_TIMEOUT_SECONDS) as client:
            response = client.put(url, json={"profile_name": profile_name})
            if response.status_code < 400:
                logger.info("Runtime accepted profile switch")
                return True
            logger.warning(
                "Runtime returned %d on profile switch: %s",
                response.status_code,
                response.text,
            )
            return False
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        logger.warning("Runtime unreachable for reload: %s", exc)
        return False


def deploy_profile(
    team: TeamSpec,
    config: StudioConfig,
    *,
    profile_name: str | None = None,
    validate_first: bool = True,
    trigger_reload: bool = True,
    force: bool = False,
) -> DeployResult:
    """Deploy a team profile to the runtime workspace.

    Args:
        team: The team specification to deploy.
        config: Studio configuration.
        profile_name: Override the profile directory name (defaults to slugified team name).
        validate_first: Run validation before deploying (recommended).
        trigger_reload: Attempt to trigger runtime reload after writing files.
        force: Override manifest ownership checks (use with caution).

    Returns:
        DeployResult with deployment status and details.

    Raises:
        DeploymentError: If deployment fails fatally.
    """
    slug = profile_name or _slugify(team.name)
    profile_dir = config.resolved_profiles_dir / slug
    result = DeployResult(success=False, profile_dir=profile_dir)

    # Validate first if requested
    if validate_first:
        validation = validate_team(team)
        if not validation.is_valid:
            result.errors = [msg.message for msg in validation.errors]
            result.warnings = [msg.message for msg in validation.warnings]
            logger.warning(
                "Deployment blocked by validation: %d errors", len(result.errors)
            )
            return result
        result.warnings = [msg.message for msg in validation.warnings]

    # Check manifest for ownership conflicts
    tracker = ManifestTracker(profile_dir)
    if not force:
        conflicts = tracker.check_conflicts()
        if conflicts:
            result.errors.extend(conflicts)
            logger.warning(
                "Deployment blocked by manifest conflicts: %s", conflicts
            )
            return result

    # Write files
    try:
        files = write_profile_to_directory(team, profile_dir)
        result.files_written = files
        logger.info("Wrote %d files to %s", len(files), profile_dir)
    except Exception as exc:
        raise DeploymentError(f"Failed to write profile files: {exc}") from exc

    # Update manifest
    try:
        tracker.update_manifest(files, ownership="studio")
    except Exception as exc:
        result.warnings.append(f"Failed to update manifest: {exc}")
        logger.warning("Manifest update failed: %s", exc, exc_info=True)

    # Trigger runtime reload
    if trigger_reload:
        result.runtime_reloaded = _trigger_reload(config, slug)
        if not result.runtime_reloaded:
            result.warnings.append(
                "Runtime reload was not triggered — files are on disk but "
                "runtime may need manual restart or reload"
            )

    result.success = True
    logger.info("Deployment complete: %s", slug)
    return result
