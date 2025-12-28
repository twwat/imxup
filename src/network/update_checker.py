"""
Background worker for checking GitHub Releases for application updates.

Provides a QThread-based worker that queries the GitHub Releases API
to check if a newer version of the application is available.

Usage:
    from src.network.update_checker import UpdateChecker

    checker = UpdateChecker(
        current_version="0.6.13",
        owner="username",
        repo="IMXuploader"
    )
    checker.update_available.connect(on_update_available)
    checker.no_update.connect(on_no_update)
    checker.check_failed.connect(on_check_failed)
    checker.start()
"""

from PyQt6.QtCore import QThread, pyqtSignal
import requests

from src.utils.logger import log
from src.core.constants import USER_AGENT


class UpdateChecker(QThread):
    """Background worker to check for application updates via GitHub Releases API.

    Queries the GitHub Releases API for the latest release and compares
    the version against the current application version.

    Signals:
        update_available: Emitted when a newer version is found.
            Args: new_version, download_url, release_notes, release_date
        no_update: Emitted when the current version is up to date.
        check_failed: Emitted when the update check fails.
            Args: error_message

    Attributes:
        GITHUB_API_URL: Template URL for GitHub Releases API.
        REQUEST_TIMEOUT: Timeout in seconds for API requests.
    """

    # Signals
    update_available = pyqtSignal(str, str, str, str)  # new_version, download_url, release_notes, release_date
    no_update = pyqtSignal()
    check_failed = pyqtSignal(str)  # error_message

    GITHUB_API_URL = "https://api.github.com/repos/{owner}/{repo}/releases/latest"
    REQUEST_TIMEOUT = 10

    def __init__(self, current_version: str, owner: str, repo: str, parent=None):
        """Initialize the update checker.

        Args:
            current_version: The current application version string (e.g., "0.6.13").
            owner: GitHub repository owner/organization name.
            repo: GitHub repository name.
            parent: Optional parent QObject.
        """
        super().__init__(parent)
        self._current_version = current_version
        self._owner = owner
        self._repo = repo

    def run(self) -> None:
        """Execute the update check in a background thread.

        Queries the GitHub Releases API and compares versions.
        Emits appropriate signals based on the result.
        """
        url = self.GITHUB_API_URL.format(owner=self._owner, repo=self._repo)
        log(f"Checking for updates at: {url}", level="debug", category="network")

        try:
            headers = {
                "User-Agent": USER_AGENT,
                "Accept": "application/vnd.github.v3+json",
            }

            response = requests.get(
                url,
                headers=headers,
                timeout=self.REQUEST_TIMEOUT,
            )

            # Handle HTTP errors
            if response.status_code == 404:
                log("No releases found for repository", level="warning", category="network")
                self.check_failed.emit("No releases found")
                return

            if response.status_code == 403:
                # Rate limit exceeded
                log("GitHub API rate limit exceeded", level="warning", category="network")
                self.check_failed.emit("GitHub API rate limit exceeded")
                return

            response.raise_for_status()

            # Parse JSON response
            data = response.json()

            tag_name = data.get("tag_name", "")
            html_url = data.get("html_url", "")
            body = data.get("body", "")
            published_at = data.get("published_at", "")

            # Strip 'v' prefix if present for version comparison
            latest_version = tag_name.lstrip("v")

            log(f"Latest release: {latest_version} (current: {self._current_version})", level="debug", category="network")

            # Compare versions
            comparison = self._compare_versions(self._current_version, latest_version)

            if comparison > 0:
                # Newer version available
                log(f"Update available: {latest_version}", level="info", category="network")
                self.update_available.emit(
                    latest_version,
                    html_url,
                    body,
                    published_at,
                )
            else:
                # Current version is up to date
                log("Application is up to date", level="debug", category="network")
                self.no_update.emit()

        except requests.Timeout:
            log("Update check timed out", level="warning", category="network")
            self.check_failed.emit("Network timeout")

        except requests.RequestException as e:
            log(f"Update check failed: {e}", level="warning", category="network")
            self.check_failed.emit(str(e))

        except (KeyError, ValueError) as e:
            log(f"Failed to parse update response: {e}", level="warning", category="network")
            self.check_failed.emit(f"Invalid response format: {e}")

    def _compare_versions(self, current: str, latest: str) -> int:
        """Compare version strings.

        Attempts to use packaging.version for accurate semantic version
        comparison, falling back to simple tuple comparison if unavailable.

        Args:
            current: Current version string.
            latest: Latest version string from GitHub.

        Returns:
            1 if latest > current (update available)
            0 if latest == current (up to date)
            -1 if latest < current (current is newer)
        """
        try:
            from packaging.version import Version
            current_ver = Version(current.lstrip("v"))
            latest_ver = Version(latest.lstrip("v"))

            if latest_ver > current_ver:
                return 1
            elif latest_ver == current_ver:
                return 0
            else:
                return -1

        except ImportError:
            # Fallback to simple tuple comparison
            log("packaging module not available, using fallback version comparison", level="debug", category="network")
            return self._compare_versions_fallback(current, latest)

    def _compare_versions_fallback(self, current: str, latest: str) -> int:
        """Fallback version comparison using tuple comparison.

        Parses version strings into tuples of integers and compares them.
        Handles versions like "0.6.13", "v0.6.13", "1.0.0-beta", etc.

        Args:
            current: Current version string.
            latest: Latest version string.

        Returns:
            1 if latest > current, 0 if equal, -1 if latest < current.
        """
        def parse_version(v: str) -> tuple:
            """Parse a version string into a tuple of integers."""
            # Strip 'v' prefix and any pre-release suffix
            v = v.lstrip("v")
            # Split on common separators and take only numeric parts
            parts = v.replace("-", ".").replace("_", ".").split(".")
            result = []
            for part in parts:
                # Extract numeric prefix from each part
                num_str = ""
                for char in part:
                    if char.isdigit():
                        num_str += char
                    else:
                        break
                if num_str:
                    result.append(int(num_str))
            return tuple(result) if result else (0,)

        current_tuple = parse_version(current)
        latest_tuple = parse_version(latest)

        if latest_tuple > current_tuple:
            return 1
        elif latest_tuple == current_tuple:
            return 0
        else:
            return -1
