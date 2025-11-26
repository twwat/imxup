# Manual Test Execution Guide

Quick reference for running path resolution and retry logic tests.

## Prerequisites

```bash
cd /home/jimbo/imxup
source ~/imxup-venv-314/bin/activate
```

## Quick Test Runs

### Run All Tests
```bash
pytest tests/integration/test_path_retry_fixes.py -v
```

### Run Specific Test Suite

**Path Resolution:**
```bash
pytest tests/integration/test_path_retry_fixes.py::TestPathResolution -v
```

**Retry Logic:**
```bash
pytest tests/integration/test_path_retry_fixes.py::TestRetryLogic -v
```

**Error Messages:**
```bash
pytest tests/integration/test_path_retry_fixes.py::TestErrorMessages -v
```

**Regression:**
```bash
pytest tests/integration/test_path_retry_fixes.py::TestRegressionCases -v
```

**ZIP Creation:**
```bash
pytest tests/integration/test_path_retry_fixes.py::TestZIPCreationWithPaths -v
```

### Run Specific Test

```bash
# Example: Test Windows path conversion
pytest tests/integration/test_path_retry_fixes.py::TestPathResolution::test_windows_path_conversion -v
```

## Test Output Options

### Detailed Output
```bash
pytest tests/integration/test_path_retry_fixes.py -vv
```

### With Coverage
```bash
pytest tests/integration/test_path_retry_fixes.py --cov=src/processing --cov=src/network --cov-report=html
```

### Generate HTML Report
```bash
pytest tests/integration/test_path_retry_fixes.py --html=tests/results/report.html --self-contained-html
```

### Generate JUnit XML
```bash
pytest tests/integration/test_path_retry_fixes.py --junit-xml=tests/results/junit.xml
```

### Comprehensive Report (All formats)
```bash
pytest tests/integration/test_path_retry_fixes.py \
    -v \
    --cov=src/processing \
    --cov=src/network \
    --cov-report=html:tests/results/coverage \
    --html=tests/results/report.html \
    --self-contained-html \
    --junit-xml=tests/results/junit.xml
```

## Automated Test Execution

### Monitor and Auto-Run
```bash
# Waits for coder, then runs all tests
./tests/scripts/monitor_coder_and_test.sh
```

### Manual Trigger (Skip Wait)
```bash
# Run tests immediately
./tests/scripts/monitor_coder_and_test.sh --skip-wait
```

## Test Filtering

### Run Only Failed Tests
```bash
pytest tests/integration/test_path_retry_fixes.py --lf
```

### Run Failed Tests First
```bash
pytest tests/integration/test_path_retry_fixes.py --ff
```

### Stop on First Failure
```bash
pytest tests/integration/test_path_retry_fixes.py -x
```

### Show Local Variables on Failure
```bash
pytest tests/integration/test_path_retry_fixes.py -l
```

## Debugging Options

### Drop into debugger on failure
```bash
pytest tests/integration/test_path_retry_fixes.py --pdb
```

### Show print statements
```bash
pytest tests/integration/test_path_retry_fixes.py -s
```

### Verbose traceback
```bash
pytest tests/integration/test_path_retry_fixes.py --tb=long
```

### Short traceback
```bash
pytest tests/integration/test_path_retry_fixes.py --tb=short
```

## Parallel Execution

```bash
# Run tests in parallel (requires pytest-xdist)
pytest tests/integration/test_path_retry_fixes.py -n auto
```

## Test Results Location

After running tests, check:
```
/home/jimbo/imxup/tests/results/
```

## Coordination Memory

### Check Tester Status
```bash
npx claude-flow@alpha memory retrieve swarm/tester/status --namespace coordination
```

### Check Test Plan
```bash
npx claude-flow@alpha memory retrieve swarm/tester/test-plan --namespace coordination
```

### Check Test Results
```bash
npx claude-flow@alpha memory retrieve swarm/tester/results --namespace coordination
```

## Common Issues

### Tests Not Found
```bash
# Make sure you're in the project root
cd /home/jimbo/imxup

# Verify test file exists
ls -l tests/integration/test_path_retry_fixes.py
```

### Import Errors
```bash
# Activate virtual environment
source ~/imxup-venv-314/bin/activate

# Verify dependencies
pip list | grep pytest
```

### Permission Errors
```bash
# Make scripts executable
chmod +x tests/scripts/*.sh
```

## Quick Smoke Test

Run a quick sanity check:
```bash
pytest tests/integration/test_path_retry_fixes.py::TestPathResolution::test_relative_path_resolution -v
```

If this passes, the test framework is working correctly.

---

**Note:** These tests are designed to run AFTER the coder implements the path resolution and retry logic fixes. Running them before implementation will result in test failures or errors.
