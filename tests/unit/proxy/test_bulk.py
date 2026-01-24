"""Unit tests for bulk proxy import/export."""

import pytest
import json

from src.proxy.models import ProxyProfile, ProxyType
from src.proxy.bulk import (
    BulkProxyParser, BulkProxyExporter, ParseResult, ParseFormat, ExportFormat,
    parse_csv_proxies, parse_json_proxies
)
# Note: Using ExportFormat enum with export() method instead of separate export_csv/export_json/export_text methods


class TestBulkProxyParser:
    """Tests for BulkProxyParser class."""

    def test_parse_ip_port_basic(self):
        """Test parsing basic IP:PORT format."""
        parser = BulkProxyParser()
        results = parser.parse_text("192.168.1.1:8080")

        assert len(results) == 1
        assert results[0].success is True
        assert results[0].profile.host == "192.168.1.1"
        assert results[0].profile.port == 8080
        assert results[0].profile.proxy_type == ProxyType.HTTP
        assert results[0].format_detected == ParseFormat.IP_PORT

    def test_parse_ip_port_with_auth(self):
        """Test parsing IP:PORT:USER:PASS format."""
        parser = BulkProxyParser()
        results = parser.parse_text("10.0.0.1:3128:myuser:mypassword")

        assert len(results) == 1
        assert results[0].success is True
        assert results[0].profile.host == "10.0.0.1"
        assert results[0].profile.port == 3128
        assert results[0].profile.auth_required is True
        assert results[0].profile.username == "myuser"
        assert results[0].password == "mypassword"
        assert results[0].format_detected == ParseFormat.IP_PORT_USER_PASS

    def test_parse_url_format(self):
        """Test parsing URL format."""
        parser = BulkProxyParser()
        results = parser.parse_text("socks5://proxy.example.com:1080")

        assert len(results) == 1
        assert results[0].success is True
        assert results[0].profile.host == "proxy.example.com"
        assert results[0].profile.port == 1080
        assert results[0].profile.proxy_type == ProxyType.SOCKS5
        assert results[0].format_detected == ParseFormat.URL

    def test_parse_url_with_auth(self):
        """Test parsing URL format with authentication."""
        parser = BulkProxyParser()
        results = parser.parse_text("http://user:pass@proxy.com:8080")

        assert len(results) == 1
        assert results[0].success is True
        assert results[0].profile.host == "proxy.com"
        assert results[0].profile.port == 8080
        assert results[0].profile.auth_required is True
        assert results[0].profile.username == "user"
        assert results[0].password == "pass"

    def test_parse_multiple_lines(self):
        """Test parsing multiple proxy lines."""
        parser = BulkProxyParser()
        text = """192.168.1.1:8080
192.168.1.2:8080
192.168.1.3:8080"""

        results = parser.parse_text(text)

        assert len(results) == 3
        assert all(r.success for r in results)
        hosts = [r.profile.host for r in results]
        assert hosts == ["192.168.1.1", "192.168.1.2", "192.168.1.3"]

    def test_skip_comments(self):
        """Test that comment lines are skipped."""
        parser = BulkProxyParser()
        text = """# This is a comment
192.168.1.1:8080
# Another comment
192.168.1.2:8080"""

        results = parser.parse_text(text)

        assert len(results) == 2

    def test_skip_empty_lines(self):
        """Test that empty lines are skipped."""
        parser = BulkProxyParser()
        text = """192.168.1.1:8080

192.168.1.2:8080

"""

        results = parser.parse_text(text)

        assert len(results) == 2

    def test_invalid_format_error(self):
        """Test that invalid formats produce errors."""
        parser = BulkProxyParser()
        results = parser.parse_text("not-a-valid-proxy-format")

        assert len(results) == 1
        assert results[0].success is False
        assert results[0].error is not None

    def test_invalid_port_error(self):
        """Test that invalid port produces error."""
        parser = BulkProxyParser()
        results = parser.parse_text("192.168.1.1:notaport")

        assert len(results) == 1
        assert results[0].success is False

    def test_custom_default_type(self):
        """Test custom default proxy type."""
        parser = BulkProxyParser(default_type=ProxyType.SOCKS5)
        results = parser.parse_text("192.168.1.1:1080")

        assert results[0].profile.proxy_type == ProxyType.SOCKS5

    def test_name_prefix(self):
        """Test custom name prefix."""
        parser = BulkProxyParser()
        results = parser.parse_text("192.168.1.1:8080", name_prefix="MyProxy")

        assert results[0].profile.name.startswith("MyProxy")

    def test_mixed_valid_invalid(self):
        """Test parsing with mix of valid and invalid lines."""
        parser = BulkProxyParser()
        text = """192.168.1.1:8080
invalid-line
192.168.1.2:8080"""

        results = parser.parse_text(text)

        assert len(results) == 3
        assert results[0].success is True
        assert results[1].success is False
        assert results[2].success is True


class TestCSVParser:
    """Tests for CSV parsing."""

    def test_parse_basic_csv(self):
        """Test parsing basic CSV format."""
        csv_content = """name,type,host,port,auth_required,username,password,enabled,bypass_list
Test1,http,proxy1.com,8080,false,,,true,
Test2,socks5,proxy2.com,1080,true,user,pass,true,localhost;127.0.0.1"""

        results = parse_csv_proxies(csv_content)

        assert len(results) == 2
        assert results[0].success is True
        assert results[0].profile.name == "Test1"
        assert results[0].profile.host == "proxy1.com"

        assert results[1].profile.proxy_type == ProxyType.SOCKS5
        assert results[1].profile.auth_required is True
        assert results[1].password == "pass"

    def test_csv_with_header_variations(self):
        """Test CSV with lowercase headers (implementation uses lowercase)."""
        csv_content = """name,type,host,port,auth_required,username,password,enabled
Test,http,test.com,8080,false,,,true"""

        results = parse_csv_proxies(csv_content)
        assert len(results) == 1
        assert results[0].success is True

    def test_csv_missing_required_fields(self):
        """Test CSV with missing required fields."""
        csv_content = """name,type
Test,http"""

        results = parse_csv_proxies(csv_content)
        # Should fail since host and port are required
        assert len(results) == 1
        assert results[0].success is False


class TestJSONParser:
    """Tests for JSON parsing."""

    def test_parse_json_array(self):
        """Test parsing JSON array of proxies."""
        # Note: from_dict expects "proxy_type" not "type"
        json_content = json.dumps([
            {
                "name": "Test1",
                "proxy_type": "http",
                "host": "proxy1.com",
                "port": 8080
            },
            {
                "name": "Test2",
                "proxy_type": "socks5",
                "host": "proxy2.com",
                "port": 1080,
                "auth_required": True,
                "username": "user",
                "password": "pass"
            }
        ])

        results = parse_json_proxies(json_content)

        assert len(results) == 2
        assert results[0].success is True
        assert results[0].profile.name == "Test1"
        assert results[1].profile.proxy_type == ProxyType.SOCKS5
        assert results[1].password == "pass"

    def test_parse_json_single_object(self):
        """Test parsing single JSON object."""
        json_content = json.dumps({
            "name": "Single",
            "host": "proxy.com",
            "port": 8080
        })

        results = parse_json_proxies(json_content)
        assert len(results) == 1
        assert results[0].success is True

    def test_invalid_json(self):
        """Test handling invalid JSON."""
        results = parse_json_proxies("not valid json")
        assert len(results) == 1
        assert results[0].success is False
        assert "JSON" in results[0].error or "json" in results[0].error.lower()


class TestBulkProxyExporter:
    """Tests for BulkProxyExporter class."""

    def test_export_csv(self):
        """Test exporting to CSV format."""
        profiles = [
            ProxyProfile(name="Test1", host="proxy1.com", port=8080),
            ProxyProfile(
                name="Test2", host="proxy2.com", port=1080,
                proxy_type=ProxyType.SOCKS5, auth_required=True, username="user"
            )
        ]
        passwords = {profiles[1].id: "secret"}

        exporter = BulkProxyExporter()
        csv_output = exporter.export(profiles, ExportFormat.CSV, passwords)

        assert "Test1" in csv_output
        assert "proxy1.com" in csv_output
        assert "8080" in csv_output
        assert "Test2" in csv_output
        assert "socks5" in csv_output
        assert "secret" in csv_output

    def test_export_json(self):
        """Test exporting to JSON format."""
        profiles = [
            ProxyProfile(name="Test1", host="proxy1.com", port=8080)
        ]

        exporter = BulkProxyExporter()
        json_output = exporter.export(profiles, ExportFormat.JSON)

        data = json.loads(json_output)
        assert len(data) == 1
        assert data[0]["name"] == "Test1"
        assert data[0]["host"] == "proxy1.com"

    def test_export_text(self):
        """Test exporting to text format."""
        profiles = [
            ProxyProfile(name="Test", host="proxy.com", port=8080, proxy_type=ProxyType.HTTP)
        ]

        exporter = BulkProxyExporter()
        text_output = exporter.export(profiles, ExportFormat.TEXT_URL)

        assert "http://proxy.com:8080" in text_output

    def test_export_text_with_auth(self):
        """Test exporting text with authentication."""
        profiles = [
            ProxyProfile(
                name="Test", host="proxy.com", port=8080,
                auth_required=True, username="user"
            )
        ]
        passwords = {profiles[0].id: "pass"}

        exporter = BulkProxyExporter()
        text_output = exporter.export(profiles, ExportFormat.TEXT_URL, passwords)

        assert "user:pass@" in text_output or "proxy.com:8080:user:pass" in text_output

    def test_round_trip_json(self):
        """Test that JSON export can be re-imported."""
        original = [
            ProxyProfile(
                name="RoundTrip",
                host="proxy.com",
                port=8080,
                proxy_type=ProxyType.SOCKS5,
                auth_required=True,
                username="user",
                bypass_list=["localhost"]
            )
        ]
        passwords = {original[0].id: "secret"}

        exporter = BulkProxyExporter()
        json_output = exporter.export(original, ExportFormat.JSON, passwords)

        # Re-import
        results = parse_json_proxies(json_output)

        assert len(results) == 1
        assert results[0].success is True
        reimported = results[0].profile
        assert reimported.name == "RoundTrip"
        assert reimported.host == "proxy.com"
        assert reimported.proxy_type == ProxyType.SOCKS5
        assert reimported.auth_required is True
