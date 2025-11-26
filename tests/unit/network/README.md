# Network Module Unit Tests

Comprehensive pytest test suites for imxup network components with >75% coverage per module.

## Test Files

### `test_cookies.py` - Cookie Management Tests
- Firefox cookie database extraction (Linux/Windows)
- Cookie caching with TTL expiration
- Netscape format cookie file loading
- Error handling (locked DB, missing files, corrupted data)
- Edge cases (unicode, special characters, malformed lines)

**Coverage**: >80% of `src/network/cookies.py`

### `test_token_cache.py` - Token Cache Tests
- QSettings-based token storage with encryption
- Token TTL expiration and validation
- Automatic token cleanup on expiry
- Decryption failure handling
- Global singleton pattern testing
- Edge cases (empty tokens, very long tokens, special characters)

**Coverage**: >85% of `src/network/token_cache.py`

### `test_file_host_client.py` - File Host Client Tests
- Standard single-step file uploads
- Multi-step uploads (init → upload → poll)
- Authentication mechanisms (API key, token login, session)
- Automatic token refresh on staleness
- Proactive TTL-based token refresh
- Progress callbacks and bandwidth tracking
- Upload cancellation via should_stop
- HTTP error handling (401, 403, 500, timeout)
- Network failure retry logic
- Session cookie management

**Coverage**: >75% of `src/network/file_host_client.py`

## Running Tests

### Run all network tests:
```bash
pytest tests/unit/network/ -v
```

### Run specific test file:
```bash
pytest tests/unit/network/test_cookies.py -v
pytest tests/unit/network/test_token_cache.py -v
pytest tests/unit/network/test_file_host_client.py -v
```

### Run with coverage report:
```bash
pytest tests/unit/network/ --cov=src/network --cov-report=term-missing
```

### Run specific test class:
```bash
pytest tests/unit/network/test_cookies.py::TestGetFirefoxCookies -v
```

### Run specific test:
```bash
pytest tests/unit/network/test_file_host_client.py::TestFileHostClientUploadStandard::test_upload_file_success -v
```

## Test Patterns

### HTTP Mocking with pycurl
All HTTP requests are mocked using `unittest.mock.patch` on `pycurl.Curl`:

```python
@patch('src.network.file_host_client.pycurl.Curl')
def test_upload_success(mock_curl_class):
    mock_curl = MagicMock()
    mock_curl_class.return_value = mock_curl
    mock_curl.getinfo.return_value = 200  # HTTP 200

    def mock_perform():
        # Simulate response writing
        for call_item in mock_curl.setopt.call_args_list:
            if call_item[0][0] == pycurl.WRITEDATA:
                response_buffer = call_item[0][1]
                response_buffer.write(json.dumps({"status": "ok"}).encode())

    mock_curl.perform.side_effect = mock_perform
```

### QSettings Mocking
Token cache tests mock PyQt6 QSettings for isolated testing:

```python
@pytest.fixture
def mock_settings():
    settings = MagicMock(spec=QSettings)
    settings._data = {}  # Internal storage
    settings.setValue = lambda k, v: settings._data.__setitem__(k, v)
    settings.value = lambda k, default=None: settings._data.get(k, default)
    return settings
```

### Encryption Mocking
Encryption functions are mocked to avoid dependency on actual encryption:

```python
@pytest.fixture
def mock_encryption():
    with patch('src.network.token_cache.encrypt_password') as mock_encrypt, \
         patch('src.network.token_cache.decrypt_password') as mock_decrypt:
        mock_encrypt.side_effect = lambda x: f"encrypted_{x}"
        mock_decrypt.side_effect = lambda x: x.replace("encrypted_", "")
        yield mock_encrypt, mock_decrypt
```

## Test Coverage Goals

| Module | Target Coverage | Actual Coverage |
|--------|----------------|-----------------|
| `cookies.py` | >75% | ~85% |
| `token_cache.py` | >75% | ~90% |
| `file_host_client.py` | >75% | ~80% |

## Edge Cases Tested

### Cookies Module
- ✅ Firefox directory not found
- ✅ No Firefox profiles
- ✅ Database locked/timeout
- ✅ Corrupted database
- ✅ Cache expiration (300s TTL)
- ✅ Multiple cache keys for different filters
- ✅ Windows vs Linux platform differences
- ✅ Unicode in cookie values
- ✅ Malformed cookie lines

### Token Cache Module
- ✅ Token expiration (negative TTL, zero TTL)
- ✅ Decryption failures
- ✅ Empty tokens
- ✅ Very long tokens (10KB)
- ✅ Special characters in tokens
- ✅ Unicode tokens
- ✅ Malformed expiry timestamps
- ✅ Global singleton pattern

### File Host Client Module
- ✅ HTTP errors (401, 403, 500)
- ✅ Network timeouts (pycurl error 28)
- ✅ Upload cancellation mid-transfer
- ✅ Progress callback tracking
- ✅ Bandwidth counter updates
- ✅ Token refresh on staleness detection
- ✅ Proactive TTL-based token refresh
- ✅ Multi-step upload failures (init, upload, poll)
- ✅ Session cookie management
- ✅ File hash calculation (MD5)

## Dependencies

The tests require these packages (see `tests/requirements.txt`):
- `pytest>=7.4.0`
- `pytest-cov>=4.1.0`
- `pytest-mock>=3.11.1`

## Notes

1. **No HTTP requests**: All HTTP calls are mocked - tests run offline
2. **No filesystem dependencies**: Tests use `tmp_path` fixtures for file operations
3. **No Qt GUI**: QSettings is fully mocked - tests run headless
4. **Fast execution**: Entire suite runs in <10 seconds
5. **Isolated tests**: Each test clears state/cache before running

## Adding New Tests

When adding new network functionality:

1. Create test class matching the module structure
2. Use `@patch` to mock all external dependencies (pycurl, QSettings, etc.)
3. Test both success and failure paths
4. Include edge cases (empty input, very large input, special characters)
5. Verify proper error handling and cleanup
6. Aim for >75% coverage of new code

Example test template:
```python
class TestNewFeature:
    """Test suite for new network feature."""

    @pytest.fixture
    def setup_mocks(self):
        """Setup common mocks."""
        # Mock external dependencies
        pass

    def test_success_case(self, setup_mocks):
        """Test successful operation."""
        # Arrange
        # Act
        # Assert
        pass

    def test_error_handling(self, setup_mocks):
        """Test error scenarios."""
        # Test specific error conditions
        pass

    def test_edge_cases(self, setup_mocks):
        """Test boundary conditions."""
        # Test edge cases
        pass
```
