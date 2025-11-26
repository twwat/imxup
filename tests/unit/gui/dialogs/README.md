# Gallery File Manager Dialog Tests

## Quick Start

```bash
# Activate virtual environment
source ~/imxup-venv-314/bin/activate

# Run all tests
python -m pytest tests/unit/gui/dialogs/test_gallery_file_manager.py -v

# Run with coverage
python -m pytest tests/unit/gui/dialogs/test_gallery_file_manager.py \
    --cov=src.gui.dialogs.gallery_file_manager \
    --cov-report=term-missing
```

## Test Results

- **Total Tests**: 50
- **Coverage**: 91%
- **Status**: All passing

## Test Categories

1. **Dialog Initialization** (4 tests)
2. **File Scanner Thread** (6 tests)
3. **File Operations** (8 tests)
4. **File Selection** (6 tests)
5. **Button State Management** (3 tests)
6. **Information Label** (4 tests)
7. **File Details Display** (4 tests)
8. **Drag and Drop** (3 tests)
9. **Completed Gallery** (3 tests)
10. **Dialog Accept/Close** (3 tests)
11. **Error Handling** (3 tests)
12. **File Status Tracking** (3 tests)

See TEST_SUMMARY.md for detailed documentation.
