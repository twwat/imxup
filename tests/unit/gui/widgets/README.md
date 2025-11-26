# GUI Widgets Unit Tests

This directory contains comprehensive unit tests for GUI widget components.

## Test Files

### test_gallery_table.py
**Comprehensive test suite for GalleryTableWidget**

- **Tests**: 61
- **Coverage Target**: 70%+
- **Lines of Code**: ~1000+
- **Source**: `src/gui/widgets/gallery_table.py` (688 lines)

**Test Categories:**
1. Initialization and Setup (13 tests)
2. NumericColumnDelegate (2 tests)
3. Row Operations (6 tests)
4. Selection Handling (5 tests)
5. Cell Editing (5 tests)
6. Context Menu (3 tests)
7. Gallery Management (6 tests)
8. Upload Status Operations (7 tests)
9. BBCode Operations (3 tests)
10. Drag and Drop (4 tests)
11. Mouse/Keyboard Events (3 tests)
12. Tab Management (1 test)
13. Scrolling and Icons (2 tests)
14. Resize Behavior (1 test)

**Quick Start:**
```bash
# Activate virtual environment
source ~/imxup-venv-314/bin/activate

# Run all tests
pytest tests/unit/gui/widgets/test_gallery_table.py -v

# Run with coverage
pytest tests/unit/gui/widgets/test_gallery_table.py --cov=src/gui/widgets/gallery_table --cov-report=term-missing

# Run specific test class
pytest tests/unit/gui/widgets/test_gallery_table.py::TestGalleryTableInit -v

# Run single test
pytest tests/unit/gui/widgets/test_gallery_table.py::TestGalleryTableInit::test_table_creates_successfully -v
```

## Test Environment

**Requirements:**
- Python 3.14.0
- pytest 9.0.1
- pytest-qt 4.5.0
- PyQt6 6.9.1
- Virtual environment: `~/imxup-venv-314`

## Test Structure

All tests follow the AAA pattern:
- **Arrange**: Set up test fixtures and mocks
- **Act**: Execute the functionality being tested
- **Assert**: Verify expected outcomes

## Fixtures

Common fixtures are provided in `tests/gui/conftest.py`:
- `qapp`: Session-scoped Qt Application
- `mock_queue_manager`: Mock QueueManager
- `mock_tab_manager`: Mock TabManager
- `mock_icon_manager`: Mock IconManager
- `gallery_table`: Configured GalleryTableWidget instance
- `sample_gallery_item`: Sample gallery data

## Writing New Tests

1. Create test class with descriptive name starting with `Test`
2. Write test methods starting with `test_`
3. Use fixtures for common setup
4. Mock external dependencies
5. Use clear, descriptive test names
6. Keep tests isolated and independent

Example:
```python
class TestMyFeature:
    """Test my new feature"""

    def test_feature_works(self, gallery_table):
        """Test that feature works correctly"""
        # Arrange
        gallery_table.insertRow(0)
        
        # Act
        result = gallery_table.some_method()
        
        # Assert
        assert result == expected_value
```

## Continuous Integration

Tests are automatically run on:
- Pull requests
- Commits to main branch
- Scheduled nightly builds

Coverage reports are generated and uploaded to coverage tracking service.

## Troubleshooting

**Tests hanging:**
- Check for modal dialogs (should be mocked)
- Verify QApplication instance exists
- Use `qtbot.wait()` for async operations

**Import errors:**
- Ensure virtual environment is activated
- Check `sys.path` includes project root
- Verify all dependencies installed

**Qt errors:**
- Ensure `qapp` fixture is used
- Use `qtbot.addWidget()` for widget cleanup
- Don't create widgets before QApplication

## See Also

- [test_gallery_table_SUMMARY.md](test_gallery_table_SUMMARY.md) - Detailed test documentation
- [../../gui/conftest.py](../../gui/conftest.py) - Shared GUI test fixtures
- [../../../gui/widgets/gallery_table.py](../../../src/gui/widgets/gallery_table.py) - Source code
