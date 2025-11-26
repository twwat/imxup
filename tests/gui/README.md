# GUI Test Suite - pytest-qt

Comprehensive test suite for ImxUp GUI components using pytest-qt.

## Test Files Generated

### Core Test Infrastructure
- **conftest.py** - Shared pytest fixtures and test utilities
  - Qt application fixture
  - Mock objects (QSettings, IconManager, QueueStore, QueueManager)
  - Temporary directories for config and assets
  - Mock credential and logging systems
  - Helper functions for signal testing

### Widget Tests
- **test_splash_screen.py** - SplashScreen widget tests (11KB, 250+ lines)
  - Initialization and setup
  - Status updates and progress dots
  - Logo loading and handling
  - Painting and rendering
  - Edge cases

- **test_icon_manager.py** - IconManager tests (15KB, 450+ lines)
  - Icon loading and caching
  - Theme handling (light/dark)
  - Legacy icon mapping
  - Status and action icons
  - Icon validation
  - Path management
  - Tooltips

- **test_tab_manager.py** - TabManager tests
  - Tab creation, deletion, retrieval
  - Preferences management
  - Tab ordering and visibility
  - Caching functionality
  - Gallery count tracking

- **test_custom_widgets.py** - Custom widget tests
  - TableProgressWidget
  - ActionButtonWidget
  - OverallProgressWidget

- **test_gallery_table.py** - GalleryTableWidget tests
  - Table initialization
  - Column management
  - NumericColumnDelegate

### Dialog Tests
- **test_help_dialog.py** - HelpDialog tests
  - Dialog initialization
  - Documentation loading
  - Tab management

- **test_credential_setup.py** - CredentialSetupDialog tests
  - Credential management
  - API key operations
  - Username/password handling

- **test_settings_dialog.py** - ComprehensiveSettingsDialog tests
  - Settings initialization
  - Configuration management

## Running Tests

### Run all GUI tests:
```bash
pytest tests/gui/ -v
```

### Run specific test file:
```bash
pytest tests/gui/test_splash_screen.py -v
```

### Run with coverage:
```bash
pytest tests/gui/ --cov=src/gui --cov-report=html
```

### Run tests matching a pattern:
```bash
pytest tests/gui/ -k "icon_manager" -v
```

### Run tests with Qt event loop debugging:
```bash
pytest tests/gui/ -v --capture=no
```

## Test Coverage

The test suite provides comprehensive coverage for:
- Widget initialization and setup
- Signal/slot connections
- User interactions (clicks, text input)
- Dialog behaviors and results
- Theme handling (light/dark mode)
- Icon loading and caching
- Configuration management
- Error handling and edge cases

## Fixtures Available

### Qt Application
- `qapp` - Session-scoped QApplication instance
- `qtbot` - pytest-qt fixture for GUI testing

### Mock Objects
- `mock_qsettings` - Mock QSettings to avoid system writes
- `mock_icon_manager` - Mock IconManager with basic functionality
- `mock_queue_store` - Mock database operations
- `mock_queue_manager` - Mock queue management
- `mock_logger` - Mock logger for testing log output

### Temporary Directories
- `temp_config_dir` - Clean config directory for tests
- `temp_assets_dir` - Assets directory with dummy icon files
- `mock_config_file` - Temporary imxup.ini config file

### Test Data
- `sample_gallery_data` - Sample gallery data for testing

## Test Structure

Each test file follows this pattern:

```python
class TestComponentInitialization:
    """Test component initialization"""
    def test_creates_successfully(self, qtbot):
        """Test that component instantiates correctly"""
        ...

class TestComponentFunctionality:
    """Test component functionality"""
    def test_specific_feature(self, qtbot):
        """Test specific feature works correctly"""
        ...

class TestComponentEdgeCases:
    """Test edge cases and error handling"""
    def test_handles_error_gracefully(self, qtbot):
        """Test error handling"""
        ...
```

## Best Practices

1. **Use qtbot** for all Qt widget interactions
2. **Wait for signals** with `qtbot.waitSignal()` or `qtbot.wait()`
3. **Mock external dependencies** using fixtures
4. **Test edge cases** and error conditions
5. **Keep tests isolated** - each test should be independent
6. **Use descriptive names** for test methods
7. **Group related tests** in classes

## Virtual Environment

Tests are designed to work with the imxup virtual environment:
```bash
source ~/imxup-venv-314/bin/activate
pytest tests/gui/ -v
```

## CI/CD Integration

Tests can be run in CI environments with:
```bash
# Install dependencies
pip install -r requirements-test.txt

# Run tests with coverage
pytest tests/gui/ --cov=src/gui --cov-report=xml

# Upload coverage to codecov
codecov -f coverage.xml
```

## Troubleshooting

### Qt Platform Plugin Issues
If you see "Could not find the Qt platform plugin":
```bash
export QT_QPA_PLATFORM=offscreen
pytest tests/gui/ -v
```

### Display Issues in Headless Environments
Use Xvfb for headless testing:
```bash
xvfb-run pytest tests/gui/ -v
```

### Slow Tests
Skip slow tests in CI:
```bash
pytest tests/gui/ -v -m "not slow"
```

## Contributing

When adding new GUI components:
1. Create corresponding test file in `tests/gui/`
2. Follow existing test structure and naming
3. Add comprehensive test coverage (aim for >80%)
4. Update this README with new test file

## Test Metrics

- **Total Test Files**: 9
- **Total Test Classes**: 40+
- **Total Test Methods**: 100+
- **Coverage Target**: >80%
- **Average Test Runtime**: <5s per file
