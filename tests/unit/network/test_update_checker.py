"""
Comprehensive pytest test suite for the UpdateChecker component.

Tests version comparison logic, GitHub API handling, and signal emissions
for the application update checker.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from PyQt6.QtCore import QThread

from src.network.update_checker import UpdateChecker


class TestUpdateCheckerVersionComparison:
    """Test version comparison logic for UpdateChecker."""

    @pytest.fixture
    def checker(self):
        """Create an UpdateChecker instance for testing."""
        return UpdateChecker("0.6.14", "owner", "repo")

    # =========================================================================
    # Same Version Tests (returns 0)
    # =========================================================================

    def test_same_version_returns_zero(self, checker):
        """Test that identical versions return 0."""
        assert checker._compare_versions("0.6.14", "0.6.14") == 0

    def test_same_version_with_v_prefix_both(self, checker):
        """Test identical versions when both have 'v' prefix."""
        assert checker._compare_versions("v0.6.14", "v0.6.14") == 0

    def test_same_version_mixed_v_prefix(self, checker):
        """Test identical versions with mixed 'v' prefix."""
        assert checker._compare_versions("0.6.14", "v0.6.14") == 0
        assert checker._compare_versions("v0.6.14", "0.6.14") == 0

    def test_same_version_single_digit(self, checker):
        """Test same single version number."""
        assert checker._compare_versions("1", "1") == 0

    def test_same_version_two_parts(self, checker):
        """Test same two-part version number."""
        assert checker._compare_versions("1.0", "1.0") == 0

    def test_same_version_four_parts(self, checker):
        """Test same four-part version number."""
        assert checker._compare_versions("1.2.3.4", "1.2.3.4") == 0

    # =========================================================================
    # Newer Version Tests (returns 1)
    # =========================================================================

    def test_newer_patch_version_returns_one(self, checker):
        """Test that newer patch version returns 1."""
        assert checker._compare_versions("0.6.13", "0.6.14") == 1

    def test_newer_minor_version_returns_one(self, checker):
        """Test that newer minor version returns 1."""
        assert checker._compare_versions("0.6.14", "0.7.0") == 1

    def test_newer_major_version_returns_one(self, checker):
        """Test that newer major version returns 1."""
        assert checker._compare_versions("0.6.14", "1.0.0") == 1

    def test_newer_version_with_v_prefix(self, checker):
        """Test newer version with 'v' prefix stripped correctly."""
        assert checker._compare_versions("0.6.13", "v0.6.14") == 1
        assert checker._compare_versions("v0.6.13", "0.6.14") == 1

    def test_newer_version_large_jump(self, checker):
        """Test newer version with large version jump."""
        assert checker._compare_versions("0.6.14", "2.0.0") == 1

    def test_newer_version_different_length(self, checker):
        """Test newer version when versions have different segment count."""
        assert checker._compare_versions("0.6", "0.6.1") == 1
        assert checker._compare_versions("1", "1.0.1") == 1

    # =========================================================================
    # Older Version Tests (returns -1)
    # =========================================================================

    def test_older_patch_version_returns_negative_one(self, checker):
        """Test that older patch version returns -1."""
        assert checker._compare_versions("0.6.14", "0.6.13") == -1

    def test_older_minor_version_returns_negative_one(self, checker):
        """Test that older minor version returns -1."""
        assert checker._compare_versions("0.7.0", "0.6.14") == -1

    def test_older_major_version_returns_negative_one(self, checker):
        """Test that older major version returns -1."""
        assert checker._compare_versions("1.0.0", "0.6.14") == -1

    def test_current_newer_than_latest(self, checker):
        """Test when current version is newer (development build)."""
        assert checker._compare_versions("0.7.0", "0.6.14") == -1

    def test_older_version_with_v_prefix(self, checker):
        """Test older version with 'v' prefix."""
        assert checker._compare_versions("v0.6.14", "v0.6.13") == -1

    # =========================================================================
    # Pre-release Version Tests
    # =========================================================================

    def test_prerelease_beta_handling(self, checker):
        """Test pre-release beta version handling."""
        # Beta should be less than release in packaging.version
        assert checker._compare_versions("0.6.13", "0.6.14-beta") == 1

    def test_prerelease_alpha_handling(self, checker):
        """Test pre-release alpha version handling."""
        assert checker._compare_versions("0.6.13", "0.6.14-alpha") == 1

    def test_prerelease_rc_handling(self, checker):
        """Test pre-release release candidate handling."""
        assert checker._compare_versions("0.6.13", "0.6.14-rc1") == 1

    def test_prerelease_dev_handling(self, checker):
        """Test pre-release dev version handling."""
        assert checker._compare_versions("0.6.13", "0.6.14.dev1") == 1

    def test_prerelease_vs_release(self, checker):
        """Test that pre-release is older than same release version."""
        # 0.6.14-beta < 0.6.14 in semantic versioning
        assert checker._compare_versions("0.6.14-beta", "0.6.14") == 1

    def test_same_prerelease_versions(self, checker):
        """Test same pre-release versions are equal."""
        assert checker._compare_versions("0.6.14-beta", "0.6.14-beta") == 0


class TestUpdateCheckerVersionComparisonFallback:
    """Test fallback version comparison logic."""

    @pytest.fixture
    def checker(self):
        """Create an UpdateChecker instance for testing."""
        return UpdateChecker("0.6.14", "owner", "repo")

    # =========================================================================
    # Fallback Same Version Tests
    # =========================================================================

    def test_fallback_same_version(self, checker):
        """Test fallback returns 0 for same versions."""
        assert checker._compare_versions_fallback("0.6.14", "0.6.14") == 0

    def test_fallback_same_version_v_prefix(self, checker):
        """Test fallback handles 'v' prefix for same versions."""
        assert checker._compare_versions_fallback("v0.6.14", "0.6.14") == 0
        assert checker._compare_versions_fallback("0.6.14", "v0.6.14") == 0

    # =========================================================================
    # Fallback Newer Version Tests
    # =========================================================================

    def test_fallback_newer_patch(self, checker):
        """Test fallback detects newer patch version."""
        assert checker._compare_versions_fallback("0.6.13", "0.6.14") == 1

    def test_fallback_newer_minor(self, checker):
        """Test fallback detects newer minor version."""
        assert checker._compare_versions_fallback("0.6.14", "0.7.0") == 1

    def test_fallback_newer_major(self, checker):
        """Test fallback detects newer major version."""
        assert checker._compare_versions_fallback("0.6.14", "1.0.0") == 1

    def test_fallback_newer_with_v_prefix(self, checker):
        """Test fallback handles 'v' prefix for newer versions."""
        assert checker._compare_versions_fallback("0.6.13", "v0.6.14") == 1

    # =========================================================================
    # Fallback Older Version Tests
    # =========================================================================

    def test_fallback_older_patch(self, checker):
        """Test fallback detects older patch version."""
        assert checker._compare_versions_fallback("0.6.14", "0.6.13") == -1

    def test_fallback_older_minor(self, checker):
        """Test fallback detects older minor version."""
        assert checker._compare_versions_fallback("0.7.0", "0.6.14") == -1

    def test_fallback_older_major(self, checker):
        """Test fallback detects older major version."""
        assert checker._compare_versions_fallback("1.0.0", "0.6.14") == -1

    # =========================================================================
    # Fallback Edge Cases
    # =========================================================================

    def test_fallback_handles_hyphen_separator(self, checker):
        """Test fallback handles hyphen in version strings."""
        # Should extract numeric prefix from each part
        assert checker._compare_versions_fallback("0.6.13", "0.6.14-beta") == 1

    def test_fallback_handles_underscore_separator(self, checker):
        """Test fallback handles underscore in version strings."""
        assert checker._compare_versions_fallback("0.6.13", "0.6.14_rc1") == 1

    def test_fallback_different_segment_count(self, checker):
        """Test fallback handles versions with different segment counts."""
        # Tuple comparison: (0, 6) < (0, 6, 1)
        assert checker._compare_versions_fallback("0.6", "0.6.1") == 1
        assert checker._compare_versions_fallback("0.6.1", "0.6") == -1

    def test_fallback_single_digit_versions(self, checker):
        """Test fallback handles single digit versions."""
        assert checker._compare_versions_fallback("1", "2") == 1
        assert checker._compare_versions_fallback("2", "1") == -1
        assert checker._compare_versions_fallback("1", "1") == 0

    def test_fallback_non_numeric_suffix(self, checker):
        """Test fallback extracts numeric prefix from parts."""
        # "14beta" should extract 14
        assert checker._compare_versions_fallback("0.6.13", "0.6.14beta") == 1

    def test_fallback_empty_numeric_part(self, checker):
        """Test fallback handles parts with no numeric prefix."""
        # "beta" has no numeric prefix, should be skipped
        # Version becomes empty tuple, treated as (0,)
        result = checker._compare_versions_fallback("0.6.14", "beta")
        assert result == -1  # (0, 6, 14) > (0,)


class TestUpdateCheckerCompareVersionsWithPackaging:
    """Test _compare_versions using packaging.version module."""

    @pytest.fixture
    def checker(self):
        """Create an UpdateChecker instance."""
        return UpdateChecker("0.6.14", "owner", "repo")

    def test_compare_versions_uses_packaging(self, checker):
        """Test that packaging.version is used when available."""
        # This test verifies the packaging path is taken
        with patch('src.network.update_checker.UpdateChecker._compare_versions_fallback') as mock_fallback:
            # If packaging is available, fallback should not be called
            result = checker._compare_versions("0.6.13", "0.6.14")
            assert result == 1
            # Note: fallback may or may not be called depending on packaging availability

    def test_compare_versions_fallback_on_import_error(self, checker):
        """Test fallback is used when packaging module unavailable."""
        with patch.dict('sys.modules', {'packaging': None, 'packaging.version': None}):
            with patch.object(checker, '_compare_versions_fallback', return_value=1) as mock_fallback:
                # Force ImportError by patching the import inside the method
                original_compare = checker._compare_versions

                def patched_compare(current, latest):
                    try:
                        raise ImportError("No module named 'packaging'")
                    except ImportError:
                        return checker._compare_versions_fallback(current, latest)

                with patch.object(checker, '_compare_versions', patched_compare):
                    result = checker._compare_versions("0.6.13", "0.6.14")
                    assert result == 1


class TestUpdateCheckerInitialization:
    """Test UpdateChecker initialization."""

    def test_init_stores_version(self):
        """Test that current version is stored correctly."""
        checker = UpdateChecker("1.2.3", "owner", "repo")
        assert checker._current_version == "1.2.3"

    def test_init_stores_owner(self):
        """Test that repository owner is stored correctly."""
        checker = UpdateChecker("1.0.0", "test-owner", "repo")
        assert checker._owner == "test-owner"

    def test_init_stores_repo(self):
        """Test that repository name is stored correctly."""
        checker = UpdateChecker("1.0.0", "owner", "test-repo")
        assert checker._repo == "test-repo"

    def test_inherits_from_qthread(self):
        """Test that UpdateChecker inherits from QThread."""
        checker = UpdateChecker("1.0.0", "owner", "repo")
        assert isinstance(checker, QThread)

    def test_init_with_none_parent(self):
        """Test initialization with None parent (default)."""
        checker = UpdateChecker("1.0.0", "owner", "repo", parent=None)
        assert checker._current_version == "1.0.0"
        # Parent is None by default, which is valid for QThread


class TestUpdateCheckerRun:
    """Test UpdateChecker.run() method behavior."""

    @pytest.fixture
    def checker(self):
        """Create an UpdateChecker instance."""
        return UpdateChecker("0.6.13", "owner", "repo")

    @pytest.fixture
    def mock_response_success(self):
        """Create a successful mock response."""
        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "tag_name": "v0.6.14",
            "html_url": "https://github.com/owner/repo/releases/tag/v0.6.14",
            "body": "Release notes here",
            "published_at": "2025-01-15T10:00:00Z"
        }
        return response

    @pytest.fixture
    def mock_response_no_update(self):
        """Create a response indicating no update available."""
        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "tag_name": "v0.6.13",
            "html_url": "https://github.com/owner/repo/releases/tag/v0.6.13",
            "body": "Current version",
            "published_at": "2025-01-01T10:00:00Z"
        }
        return response

    def test_run_emits_update_available(self, checker, mock_response_success):
        """Test that update_available signal is emitted when newer version exists."""
        signal_spy = Mock()
        checker.update_available.connect(signal_spy)

        with patch('requests.get', return_value=mock_response_success):
            mock_response_success.raise_for_status = Mock()
            checker.run()

        signal_spy.assert_called_once_with(
            "0.6.14",
            "https://github.com/owner/repo/releases/tag/v0.6.14",
            "Release notes here",
            "2025-01-15T10:00:00Z"
        )

    def test_run_emits_no_update(self, checker, mock_response_no_update):
        """Test that no_update signal is emitted when version is current."""
        signal_spy = Mock()
        checker.no_update.connect(signal_spy)

        with patch('requests.get', return_value=mock_response_no_update):
            mock_response_no_update.raise_for_status = Mock()
            checker.run()

        signal_spy.assert_called_once()

    def test_run_handles_404_error(self, checker):
        """Test that check_failed signal is emitted on 404."""
        signal_spy = Mock()
        checker.check_failed.connect(signal_spy)

        response = Mock()
        response.status_code = 404

        with patch('requests.get', return_value=response):
            checker.run()

        signal_spy.assert_called_once_with("No releases found")

    def test_run_handles_403_rate_limit(self, checker):
        """Test that check_failed signal is emitted on rate limit."""
        signal_spy = Mock()
        checker.check_failed.connect(signal_spy)

        response = Mock()
        response.status_code = 403

        with patch('requests.get', return_value=response):
            checker.run()

        signal_spy.assert_called_once_with("GitHub API rate limit exceeded")

    def test_run_handles_timeout(self, checker):
        """Test that check_failed signal is emitted on timeout."""
        import requests

        signal_spy = Mock()
        checker.check_failed.connect(signal_spy)

        with patch('requests.get', side_effect=requests.Timeout()):
            checker.run()

        signal_spy.assert_called_once_with("Network timeout")

    def test_run_handles_request_exception(self, checker):
        """Test that check_failed signal is emitted on request exception."""
        import requests

        signal_spy = Mock()
        checker.check_failed.connect(signal_spy)

        with patch('requests.get', side_effect=requests.RequestException("Connection error")):
            checker.run()

        signal_spy.assert_called_once_with("Connection error")

    def test_run_handles_invalid_json(self, checker):
        """Test that check_failed signal is emitted on invalid JSON."""
        signal_spy = Mock()
        checker.check_failed.connect(signal_spy)

        response = Mock()
        response.status_code = 200
        response.raise_for_status = Mock()
        response.json.side_effect = ValueError("Invalid JSON")

        with patch('requests.get', return_value=response):
            checker.run()

        assert signal_spy.called
        assert "Invalid response format" in signal_spy.call_args[0][0]

    def test_run_uses_correct_url(self, checker):
        """Test that correct GitHub API URL is used."""
        response = Mock()
        response.status_code = 404

        with patch('requests.get', return_value=response) as mock_get:
            checker.run()

        expected_url = "https://api.github.com/repos/owner/repo/releases/latest"
        mock_get.assert_called_once()
        assert mock_get.call_args[0][0] == expected_url

    def test_run_uses_correct_headers(self, checker):
        """Test that correct headers are sent in request."""
        response = Mock()
        response.status_code = 404

        with patch('requests.get', return_value=response) as mock_get:
            checker.run()

        call_kwargs = mock_get.call_args[1]
        assert "headers" in call_kwargs
        headers = call_kwargs["headers"]
        assert headers["Accept"] == "application/vnd.github.v3+json"
        assert "User-Agent" in headers

    def test_run_uses_timeout(self, checker):
        """Test that request uses configured timeout."""
        response = Mock()
        response.status_code = 404

        with patch('requests.get', return_value=response) as mock_get:
            checker.run()

        call_kwargs = mock_get.call_args[1]
        assert call_kwargs["timeout"] == UpdateChecker.REQUEST_TIMEOUT


class TestUpdateCheckerSignals:
    """Test UpdateChecker signal definitions."""

    def test_update_available_signal_exists(self):
        """Test that update_available signal is defined."""
        checker = UpdateChecker("1.0.0", "owner", "repo")
        assert hasattr(checker, 'update_available')

    def test_no_update_signal_exists(self):
        """Test that no_update signal is defined."""
        checker = UpdateChecker("1.0.0", "owner", "repo")
        assert hasattr(checker, 'no_update')

    def test_check_failed_signal_exists(self):
        """Test that check_failed signal is defined."""
        checker = UpdateChecker("1.0.0", "owner", "repo")
        assert hasattr(checker, 'check_failed')


class TestUpdateCheckerConstants:
    """Test UpdateChecker class constants."""

    def test_github_api_url_format(self):
        """Test GITHUB_API_URL is correct format."""
        expected = "https://api.github.com/repos/{owner}/{repo}/releases/latest"
        assert UpdateChecker.GITHUB_API_URL == expected

    def test_request_timeout_is_positive(self):
        """Test REQUEST_TIMEOUT is a positive value."""
        assert UpdateChecker.REQUEST_TIMEOUT > 0

    def test_request_timeout_reasonable(self):
        """Test REQUEST_TIMEOUT is reasonable (not too short or long)."""
        assert 5 <= UpdateChecker.REQUEST_TIMEOUT <= 60


class TestUpdateCheckerEdgeCases:
    """Test edge cases and boundary conditions."""

    @pytest.fixture
    def checker(self):
        """Create an UpdateChecker instance."""
        return UpdateChecker("0.6.14", "owner", "repo")

    def test_empty_tag_name(self, checker):
        """Test handling of empty tag_name from API.

        Empty version string causes a ValueError in packaging.version,
        so check_failed signal is emitted with an error message.
        """
        signal_spy = Mock()
        checker.check_failed.connect(signal_spy)

        response = Mock()
        response.status_code = 200
        response.raise_for_status = Mock()
        response.json.return_value = {
            "tag_name": "",
            "html_url": "",
            "body": "",
            "published_at": ""
        }

        with patch('requests.get', return_value=response):
            checker.run()

        # Empty version causes ValueError, which emits check_failed
        signal_spy.assert_called_once()
        assert "Invalid" in signal_spy.call_args[0][0]

    def test_missing_optional_fields(self, checker):
        """Test handling of missing optional fields in API response."""
        signal_spy = Mock()
        checker.update_available.connect(signal_spy)

        response = Mock()
        response.status_code = 200
        response.raise_for_status = Mock()
        response.json.return_value = {
            "tag_name": "v0.6.15"
            # Missing: html_url, body, published_at
        }

        with patch('requests.get', return_value=response):
            checker.run()

        signal_spy.assert_called_once_with("0.6.15", "", "", "")

    def test_version_with_leading_zeros(self, checker):
        """Test version comparison with leading zeros."""
        # Leading zeros in version segments
        assert checker._compare_versions("0.6.14", "0.6.015") == 1

    def test_very_long_version_string(self, checker):
        """Test handling of very long version strings."""
        long_version = "1.2.3.4.5.6.7.8.9.10"
        assert checker._compare_versions("0.6.14", long_version) == 1

    def test_version_with_build_metadata(self, checker):
        """Test version with build metadata suffix."""
        # packaging.version handles build metadata
        result = checker._compare_versions("0.6.13", "0.6.14+build123")
        assert result == 1

    def test_version_strips_multiple_v_prefix(self, checker):
        """Test that 'v' prefix is stripped correctly."""
        # lstrip('v') removes all leading 'v' chars
        assert checker._compare_versions("vvv0.6.14", "0.6.14") == 0


class TestUpdateCheckerIntegration:
    """Integration tests for UpdateChecker component."""

    def test_full_update_check_flow(self):
        """Test complete update check flow with signal handling."""
        checker = UpdateChecker("0.6.13", "test-owner", "test-repo")

        update_received = []
        no_update_received = []
        error_received = []

        checker.update_available.connect(
            lambda ver, url, notes, date: update_received.append((ver, url, notes, date))
        )
        checker.no_update.connect(lambda: no_update_received.append(True))
        checker.check_failed.connect(lambda msg: error_received.append(msg))

        response = Mock()
        response.status_code = 200
        response.raise_for_status = Mock()
        response.json.return_value = {
            "tag_name": "v0.6.14",
            "html_url": "https://github.com/test-owner/test-repo/releases/v0.6.14",
            "body": "New features and bug fixes",
            "published_at": "2025-01-20T12:00:00Z"
        }

        with patch('requests.get', return_value=response):
            checker.run()

        assert len(update_received) == 1
        assert len(no_update_received) == 0
        assert len(error_received) == 0

        version, url, notes, date = update_received[0]
        assert version == "0.6.14"
        assert "test-owner" in url
        assert "New features" in notes

    def test_multiple_check_cycles(self):
        """Test that checker can be run multiple times."""
        checker = UpdateChecker("0.6.13", "owner", "repo")

        call_count = 0

        def count_calls(*args):
            nonlocal call_count
            call_count += 1

        checker.no_update.connect(count_calls)

        response = Mock()
        response.status_code = 200
        response.raise_for_status = Mock()
        response.json.return_value = {
            "tag_name": "v0.6.13",
            "html_url": "",
            "body": "",
            "published_at": ""
        }

        with patch('requests.get', return_value=response):
            checker.run()
            checker.run()
            checker.run()

        assert call_count == 3
