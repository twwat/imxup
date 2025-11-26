# Test Suite Quick Start

## 🚀 Run Tests Immediately

```bash
# 1. Install dependencies (one-time setup)
pip install -r tests/requirements.txt

# 2. Run all tests with coverage
pytest --cov=swarm --cov-report=html --cov-report=term

# 3. View coverage report
open htmlcov/index.html  # macOS
xdg-open htmlcov/index.html  # Linux
```

## 📊 What Gets Tested

- ✅ **125+ Unit Tests** - Configuration, memory, hooks
- ✅ **25+ Integration Tests** - Swarm initialization, coordination
- ✅ **20+ Performance Tests** - Concurrent ops, latency benchmarks
- ✅ **>80% Coverage Target** - All metrics

## ⚡ Quick Commands

```bash
# Unit tests only (fast)
pytest tests/unit/ -v

# Integration tests
pytest tests/integration/ -v

# Performance benchmarks
pytest tests/performance/ -v

# Parallel execution (faster)
pytest -n auto

# Skip slow tests
pytest -m "not slow"

# Single test file
pytest tests/unit/test_config_validation.py -v

# With detailed output
pytest -vv -s
```

## 📈 Coverage Requirements

All metrics must be >80%:
- Statement Coverage
- Branch Coverage
- Function Coverage
- Line Coverage

## 🎯 Performance Benchmarks

- 5 concurrent agents: <60s
- Memory read: <10ms
- Memory write: <50ms
- Hook overhead: <5% of task time

## 📁 Test Files

```
tests/
├── conftest.py              # Shared fixtures
├── unit/                    # 125+ unit tests
│   ├── test_config_validation.py
│   ├── test_memory_coordination.py
│   └── test_hook_execution.py
├── integration/             # 25+ integration tests
│   └── test_swarm_initialization.py
└── performance/             # 20+ performance tests
    └── test_concurrent_operations.py
```

## 📚 Documentation

- **Full Test Plan:** `/mnt/h/cursor/imxup/swarm/docs/test-plan.md`
- **Test Suite README:** `/mnt/h/cursor/imxup/tests/README.md`
- **Summary Report:** `/mnt/h/cursor/imxup/swarm/results/test-summary-report.md`

## 🐛 Troubleshooting

**Import errors:**
```bash
export PYTHONPATH=/mnt/h/cursor/imxup:$PYTHONPATH
pytest
```

**Slow tests:**
```bash
pytest -n auto  # Parallel execution
```

**Coverage below 80%:**
```bash
pytest --cov=swarm --cov-report=term-missing  # See missing lines
```

## ✅ Success Criteria

- All tests passing
- Coverage >80% (all metrics)
- Performance benchmarks met
- No critical bugs

---

**Ready to run!** Just execute: `pytest --cov=swarm --cov-report=html`
