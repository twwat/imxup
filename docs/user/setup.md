# Development Environment Setup

## Python Environment

### Virtual Environment Location
**Location:** `~/imxup-venv-314`
**Python Version:** 3.14.0
**Created:** November 13, 2025

### Activation
```bash
# Activate the venv
source ~/imxup-venv-314/bin/activate

# Verify Python version
python --version  # Should show Python 3.14.0

# Verify pip
pip --version
```

### Deactivation
```bash
deactivate
```

## Project Structure

```
/mnt/h/cursor/imxup/
├── src/                    # Source code
│   ├── core/              # Core application logic
│   ├── gui/               # PyQt6 GUI components
│   ├── network/           # Network operations
│   ├── processing/        # Workers and tasks
│   ├── storage/           # Database and queue management
│   ├── utils/             # Utility functions
│   └── init/              # Initialization modules
├── tests/                 # Test suite
│   ├── unit/             # Unit tests (NEW - generated)
│   │   ├── core/
│   │   ├── storage/
│   │   ├── network/
│   │   ├── utils/
│   │   └── processing/
│   ├── integration/       # Integration tests
│   └── performance/       # Performance tests
├── swarm/                 # Swarm coordination files
├── docs/                  # Documentation
└── pytest.ini            # Pytest configuration (FIXED)
```

## Dependencies

### Core Dependencies
- Python 3.14+
- PyQt6 (GUI framework)
- pycurl (HTTP client)
- Pillow (Image processing)

### Testing Dependencies
Installed in `~/imxup-venv-314`:
- pytest 9.0.1
- pytest-cov 7.0.0
- pytest-mock 3.15.1
- pytest-asyncio 1.3.0
- pytest-xdist 3.8.0
- pytest-benchmark 5.2.3
- And more... (see tests/requirements.txt)

## Running Tests

### All Tests
```bash
# Activate venv first
source ~/imxup-venv-314/bin/activate

# Run all tests (pytest.ini configured with pythonpath)
pytest

# Or explicitly
pytest tests/
```

### With Coverage
```bash
# Full coverage report
pytest --cov=src --cov-report=html

# View coverage
explorer.exe htmlcov/index.html  # WSL
xdg-open htmlcov/index.html      # Linux
```

### Specific Test Modules
```bash
# Core tests
pytest tests/unit/core/

# Storage tests
pytest tests/unit/storage/

# Network tests
pytest tests/unit/network/

# Single test file
pytest tests/unit/core/test_constants.py -v
```

## Pytest Configuration

**File:** `/mnt/h/cursor/imxup/pytest.ini`

**Key Settings:**
- `pythonpath = .` - Allows `from src.module import ...`
- `--cov=src` - Coverage for source code
- `--cov-fail-under=40` - Minimum 40% coverage required
- Test discovery: `test_*.py` patterns
- HTML coverage reports in `htmlcov/`

## Quick Start

```bash
# 1. Navigate to project
cd /mnt/h/cursor/imxup

# 2. Activate venv
source ~/imxup-venv-314/bin/activate

# 3. Run tests
pytest

# 4. View coverage
explorer.exe htmlcov/index.html
```

## Troubleshooting

### Import Errors
If you see `ModuleNotFoundError: No module named 'src'`:

**Solution:** pytest.ini is now configured with `pythonpath = .`

If still having issues:
```bash
export PYTHONPATH=/mnt/h/cursor/imxup:$PYTHONPATH
```

### Missing Dependencies
```bash
# Install testing dependencies
pip install -r tests/requirements.txt

# Install Pillow (for image tests)
pip install Pillow
```

### Wrong Python Version
```bash
# Verify you're using Python 3.14
python --version

# If not, check venv activation
which python
# Should show: /home/jimbo/imxup-venv-314/bin/python
```

## Development Workflow

### 1. Make Changes
Edit source files in `src/`

### 2. Run Tests
```bash
pytest tests/unit/core/  # Test your module
```

### 3. Check Coverage
```bash
pytest --cov=src.core.engine tests/unit/core/test_engine.py
```

### 4. Commit
```bash
git add .
git commit -m "Your changes"
```

## CI/CD Integration

Tests are configured to run in CI/CD pipelines:
- Minimum Python 3.14
- Install from `tests/requirements.txt`
- Run `pytest` (uses pytest.ini settings)
- Generate coverage reports
- Fail if coverage < 40%

## Notes

- Virtual environment is in **home directory** (`~/imxup-venv-314`) to avoid WSL/Windows filesystem issues
- Old Windows venv in project root can be ignored
- All new tests should go in `tests/unit/` or `tests/integration/`
- Coverage target: 80% (currently ~45-55% with generated tests)

---

**Last Updated:** November 13, 2025
**Python Version:** 3.14.0
**Venv Location:** ~/imxup-venv-314
