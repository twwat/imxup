# imxup Swarm Test Suite

Comprehensive test suite for the imxup initialization system and swarm coordination.

## Overview

This test suite provides comprehensive coverage of the initialization system with unit tests, integration tests, and performance benchmarks.

## Test Structure

```
tests/
├── conftest.py              # Shared fixtures and configuration
├── requirements.txt         # Testing dependencies
├── unit/                    # Unit tests (50% of test pyramid)
│   ├── test_config_validation.py
│   ├── test_memory_coordination.py
│   └── test_hook_execution.py
├── integration/             # Integration tests (35% of test pyramid)
│   └── test_swarm_initialization.py
└── performance/             # Performance tests (15% of test pyramid)
    └── test_concurrent_operations.py
```

## Quick Start

### Installation

```bash
# Install testing dependencies
pip install -r tests/requirements.txt

# Or install with main project
pip install -r requirements.txt
```

### Running Tests

```bash
# Run all tests
pytest

# Run specific test suite
pytest tests/unit/
pytest tests/integration/
pytest tests/performance/

# Run with coverage
pytest --cov=swarm --cov-report=html

# Run specific test file
pytest tests/unit/test_config_validation.py

# Run specific test
pytest tests/unit/test_config_validation.py::TestSwarmConfigValidation::test_valid_config_parsing

# Run tests by marker
pytest -m unit
pytest -m integration
pytest -m performance
pytest -m "not slow"
```

### Parallel Execution

```bash
# Run tests in parallel (faster)
pytest -n auto

# Run with specific number of workers
pytest -n 4
```

## Test Categories

### Unit Tests

Test individual components in isolation:

- **Configuration Validation** (`test_config_validation.py`)
  - Swarm configuration parsing
  - Objective detection
  - Agent instructions validation
  - Edge cases and error handling

- **Memory Coordination** (`test_memory_coordination.py`)
  - Memory storage/retrieval
  - Namespace isolation
  - Cross-agent coordination
  - Transaction consistency

- **Hook Execution** (`test_hook_execution.py`)
  - Pre-task hooks
  - Post-task hooks
  - Hook pipeline
  - Performance overhead

### Integration Tests

Test component interactions:

- **Swarm Initialization** (`test_swarm_initialization.py`)
  - Full initialization workflow
  - Agent spawning coordination
  - Memory persistence
  - Hook integration
  - End-to-end scenarios

### Performance Tests

Benchmark system performance:

- **Concurrent Operations** (`test_concurrent_operations.py`)
  - Multi-agent execution (5 concurrent agents <60s)
  - Memory operation latency (<10ms read, <50ms write)
  - Hook execution overhead (<100ms, <5% of task time)
  - Scalability benchmarks

## Coverage Requirements

| Metric | Target | Status |
|--------|--------|--------|
| Statement Coverage | >80% | Pending |
| Branch Coverage | >75% | Pending |
| Function Coverage | >80% | Pending |
| Line Coverage | >80% | Pending |

### Viewing Coverage

```bash
# Generate HTML coverage report
pytest --cov=swarm --cov-report=html

# Open in browser
open htmlcov/index.html

# Terminal report
pytest --cov=swarm --cov-report=term-missing

# JSON report
pytest --cov=swarm --cov-report=json
```

## Test Fixtures

Shared fixtures are defined in `conftest.py`:

- `temp_dir` - Temporary directory for test files
- `temp_memory_db` - Temporary SQLite database
- `sample_swarm_config` - Sample swarm configuration
- `sample_agent_instructions` - Sample agent instructions
- `sample_objective` - Sample objective data
- `mock_file_system` - Mock file system structure
- `mock_claude_flow_client` - Mock MCP client

## Test Markers

Use markers to categorize and run specific tests:

```bash
# Unit tests only
pytest -m unit

# Integration tests only
pytest -m integration

# Performance tests only
pytest -m performance

# Exclude slow tests
pytest -m "not slow"

# Run only smoke tests (quick validation)
pytest -m smoke
```

## Writing Tests

### Test Naming Convention

- Test files: `test_*.py` or `*_test.py`
- Test classes: `Test*`
- Test functions: `test_*`

### Example Test

```python
import pytest

@pytest.mark.unit
class TestMyFeature:
    """Test my feature."""

    def test_basic_functionality(self, temp_dir):
        """Test basic functionality works."""
        # Arrange
        data = {"key": "value"}

        # Act
        result = process_data(data)

        # Assert
        assert result["key"] == "value"
        assert result["processed"] is True
```

### Using Fixtures

```python
def test_with_fixtures(temp_memory_db, sample_swarm_config):
    """Test using shared fixtures."""
    # temp_memory_db is a SQLite connection
    # sample_swarm_config is test data

    temp_memory_db.execute(...)
    assert sample_swarm_config["swarmId"] == "test-swarm-001"
```

## Performance Benchmarks

### Requirements

- 5 concurrent agents complete in <60 seconds
- Memory read operations <10ms
- Memory write operations <50ms
- Bulk operations (100 records) <500ms
- Hook overhead <5% of task execution time
- Parallel speedup >2x over sequential

### Running Benchmarks

```bash
# Run performance tests
pytest tests/performance/ -v

# Show benchmark results
pytest tests/performance/ --benchmark-only

# Save benchmark results
pytest tests/performance/ --benchmark-save=baseline

# Compare against baseline
pytest tests/performance/ --benchmark-compare=baseline
```

## Quality Gates

Tests must pass these gates for production readiness:

1. ✅ All unit tests passing
2. ✅ All integration tests passing
3. ✅ Coverage >80% (all metrics)
4. ✅ Performance benchmarks met
5. ✅ No critical bugs
6. ✅ No high-priority bugs >5

## Continuous Integration

### GitHub Actions Example

```yaml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.14'
      - run: pip install -r tests/requirements.txt
      - run: pytest --cov=swarm --cov-report=xml
      - uses: codecov/codecov-action@v3
```

## Debugging Tests

### Verbose Output

```bash
# Very verbose
pytest -vv

# Show print statements
pytest -s

# Show local variables on failure
pytest -l --tb=long
```

### Running Single Test

```bash
# Run one test for debugging
pytest tests/unit/test_config_validation.py::TestSwarmConfigValidation::test_valid_config_parsing -vv -s
```

### Using pdb

```python
def test_with_debugging():
    """Test with debugging."""
    data = {"key": "value"}

    # Drop into debugger
    import pdb; pdb.set_trace()

    result = process_data(data)
    assert result is not None
```

## Test Data

Test data is organized in:

- `conftest.py` - Shared fixtures
- `tests/data/` - Test data files (if needed)
- Inline test data in test files

## Troubleshooting

### Common Issues

**Import errors:**
```bash
# Add project root to PYTHONPATH
export PYTHONPATH=/mnt/h/cursor/imxup:$PYTHONPATH
pytest
```

**Database locked:**
```bash
# Close all database connections
# Use separate database per test with fixtures
```

**Slow tests:**
```bash
# Run in parallel
pytest -n auto

# Skip slow tests
pytest -m "not slow"
```

## Documentation

- [Test Plan](/mnt/h/cursor/imxup/swarm/docs/test-plan.md) - Comprehensive testing strategy
- [pytest Documentation](https://docs.pytest.org/) - pytest framework docs
- [Coverage.py](https://coverage.readthedocs.io/) - Coverage tool docs

## Contributing

When adding new tests:

1. Follow existing structure and naming conventions
2. Add appropriate markers (`@pytest.mark.unit`, etc.)
3. Use fixtures from `conftest.py`
4. Ensure tests are isolated and repeatable
5. Update this README if adding new test categories
6. Maintain >80% coverage

## Test Results

Current test results are tracked in `/mnt/h/cursor/imxup/swarm/results/test-results.json`.

## Support

For questions or issues with tests:

1. Check this README
2. Review test plan documentation
3. Examine existing test examples
4. Contact QA engineer agent

---

**Status:** Test suite created and ready for execution
**Coverage Target:** >80% all metrics
**Last Updated:** 2025-11-13
