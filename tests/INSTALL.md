# Testing Setup Guide

## Installation Steps

### 1. Install Testing Dependencies

From the project root (`/mnt/h/cursor/imxup`):

```bash
# Navigate to project directory
cd /mnt/h/cursor/imxup

# Install test dependencies
pip3 install -r tests/requirements.txt

# Or use pip (without the 3)
pip install -r tests/requirements.txt
```

### 2. Verify Installation

```bash
# Check pytest is installed
pytest --version

# Check pytest-cov is installed
pytest --help | grep cov
```

### 3. Run Tests

```bash
# Run all tests with coverage
pytest --cov=swarm --cov-report=html

# Run specific test categories
pytest tests/unit/              # Unit tests only
pytest tests/integration/       # Integration tests only
pytest tests/performance/       # Performance tests only

# Run with verbose output
pytest -v --cov=swarm

# Run in parallel (faster)
pytest -n auto --cov=swarm
```

### 4. View Coverage Report

After running tests with `--cov-report=html`:

```bash
# Open the coverage report in browser
xdg-open htmlcov/index.html

# Or on Windows WSL
explorer.exe htmlcov/index.html

# Or just view the text summary
pytest --cov=swarm --cov-report=term
```

## Common Issues

### Issue: "pytest: error: unrecognized arguments: --cov"

**Solution**: Install pytest-cov:
```bash
pip3 install pytest-cov
```

### Issue: "No module named 'swarm'"

**Solution**: You need to create the swarm module first or adjust the path:
```bash
# Run tests from project root
cd /mnt/h/cursor/imxup
pytest --cov=src --cov-report=html
```

### Issue: "Permission denied"

**Solution**: Use user install:
```bash
pip3 install --user -r tests/requirements.txt
```

## Quick Start

```bash
# One-liner to install and run tests
cd /mnt/h/cursor/imxup && pip3 install -r tests/requirements.txt && pytest --cov=src --cov-report=html
```

## Alternative: Run Without Coverage

If you just want to run tests without coverage:

```bash
cd /mnt/h/cursor/imxup
pytest tests/
```
