# Core Module Tests

Comprehensive pytest test suite for imxup core modules with >80% coverage target.

## Test Files

### test_engine.py (908 lines)
Tests for `src/core/engine.py` - Main upload engine

**Coverage Areas:**
- ✅ AtomicCounter thread-safe operations (8 tests)
- ✅ ByteCountingCallback progress tracking (6 tests)
- ✅ UploadEngine initialization (3 tests)
- ✅ File gathering and natural sorting (4 tests)
- ✅ Gallery creation workflows (new, resume, append) (3 tests)
- ✅ Upload operations and concurrency (2 tests)
- ✅ Progress callbacks and soft stop (3 tests)
- ✅ Statistics and results aggregation (3 tests)
- ✅ Edge cases and error handling (3 tests)
- ✅ Integration tests (1 test)

**Total: 36 test methods across 10 test classes**

### test_file_host_config.py (769 lines)
Tests for `src/core/file_host_config.py` - File host configuration system

**Coverage Areas:**
- ✅ HostConfig dataclass initialization (7 tests)
- ✅ FileHostConfigManager loading (9 tests)
- ✅ Settings management (INI persistence) (9 tests)
- ✅ Enable/disable and trigger filtering (6 tests)
- ✅ Thread safety and INI operations (2 tests)
- ✅ Singleton pattern (2 tests)

**Total: 35 test methods across 6 test classes**

### test_constants.py (716 lines)
Tests for `src/core/constants.py` - Application constants

**Coverage Areas:**
- ✅ Application info (2 tests)
- ✅ Network configuration (4 tests)
- ✅ File size constants (5 tests)
- ✅ File size limits (3 tests)
- ✅ Image processing (4 tests)
- ✅ Thumbnail configuration (6 tests)
- ✅ Gallery settings (2 tests)
- ✅ Progress updates (2 tests)
- ✅ URLs and endpoints (4 tests)
- ✅ HTTP status codes (6 tests)
- ✅ Queue states (2 tests)
- ✅ Logging configuration (3 tests)
- ✅ GUI settings (4 tests)
- ✅ Performance settings (3 tests)
- ✅ File paths (3 tests)
- ✅ Template placeholders (4 tests)
- ✅ Encryption settings (2 tests)
- ✅ Time formats (3 tests)
- ✅ Message constants (2 tests)
- ✅ Worker thread settings (2 tests)
- ✅ Database settings (3 tests)
- ✅ Rate limiting (2 tests)
- ✅ Memory management (2 tests)
- ✅ Testing constants (2 tests)
- ✅ Integration tests (4 tests)

**Total: 79 test methods across 25 test classes**

## Running Tests

### Run All Core Tests
```bash
pytest tests/unit/core/ -v
```

### Run Specific Module Tests
```bash
pytest tests/unit/core/test_engine.py -v
pytest tests/unit/core/test_file_host_config.py -v
pytest tests/unit/core/test_constants.py -v
```

### Run with Coverage Report
```bash
pytest tests/unit/core/ --cov=src/core --cov-report=html --cov-report=term
```

### Run Specific Test Classes
```bash
pytest tests/unit/core/test_engine.py::TestAtomicCounter -v
pytest tests/unit/core/test_file_host_config.py::TestHostConfig -v
pytest tests/unit/core/test_constants.py::TestFileSizeConstants -v
```

### Run with Markers
```bash
pytest tests/unit/core/ -m unit -v
```

## Test Strategy

### AAA Pattern (Arrange-Act-Assert)
All tests follow the Arrange-Act-Assert pattern:
```python
def test_example(self):
    # Arrange - Set up test data and mocks
    counter = AtomicCounter()

    # Act - Execute the code being tested
    counter.add(100)

    # Assert - Verify the expected outcome
    assert counter.get() == 100
```

### Parametrized Tests
Multiple test cases executed with different inputs:
```python
@pytest.mark.parametrize("values,expected", [
    ([1, 2, 3], 6),
    ([100, 200], 300),
])
def test_with_params(self, values, expected):
    # Test logic
```

### Fixtures
Shared test setup using pytest fixtures:
```python
@pytest.fixture
def temp_image_folder(self):
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)
```

### Mocking
External dependencies mocked for isolation:
```python
mock_uploader = Mock()
mock_uploader.upload_image.return_value = {
    'status': 'success',
    'data': {'gallery_id': 'test123'}
}
```

## Coverage Goals

**Target: >80% coverage per module**

- **Statements:** >80%
- **Branches:** >75%
- **Functions:** >80%
- **Lines:** >80%

## Test Categories

### Unit Tests
- Isolated component testing
- Fast execution (<100ms per test)
- No external dependencies
- Comprehensive edge case coverage

### Integration Tests
- Component interaction testing
- End-to-end workflows
- Real file system operations (with cleanup)
- Multi-threaded scenarios

### Edge Cases
- Boundary values
- Empty/null inputs
- Error conditions
- Concurrent access
- Resource exhaustion

## Key Testing Patterns

### Thread Safety Testing
```python
def test_counter_thread_safety(self):
    counter = AtomicCounter()
    threads = [threading.Thread(target=increment) for _ in range(10)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert counter.get() == expected
```

### Error Handling Testing
```python
def test_engine_handles_upload_failures(self):
    mock_uploader.upload_image.return_value = {
        'status': 'error',
        'message': 'Network error'
    }
    # Verify graceful failure handling
```

### Callback Testing
```python
def test_progress_callback_is_called(self):
    progress_calls = []
    def progress_cb(completed, total, percent, filename):
        progress_calls.append((completed, total, percent))

    engine.run(..., on_progress=progress_cb)
    assert len(progress_calls) >= expected
```

## Dependencies

Tests use these fixtures and utilities from `tests/conftest.py`:
- `temp_dir` - Temporary directory with auto-cleanup
- `mock_file_system` - Mock file structure
- `assert_helpers` - Custom assertion utilities

## Continuous Integration

These tests are designed to run in CI/CD pipelines:
- Fast execution (full suite <5 minutes)
- No external service dependencies
- Deterministic results
- Comprehensive coverage reporting

## Contributing

When adding new tests:
1. Follow AAA pattern (Arrange-Act-Assert)
2. Use descriptive test names explaining what and why
3. Include docstrings for complex tests
4. Mock external dependencies
5. Clean up resources (files, threads, etc.)
6. Aim for >80% coverage on new code
7. Group related tests in classes

## Summary

**Total Test Coverage:**
- **150 test methods** across 41 test classes
- **2,393 lines** of comprehensive test code
- **>80% coverage target** for all core modules
- **Thread-safe** concurrent testing
- **Edge case coverage** for robustness
- **Integration tests** for workflows
