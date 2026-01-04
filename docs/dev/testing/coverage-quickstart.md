# Get to 80% Coverage - Quick Start Guide

## 🎯 Your Goal
**Current:** 4.53% coverage (1,002 / 22,112 lines)
**Target:** 80% coverage (17,690 / 22,112 lines)
**Gap:** Need to test ~16,688 more lines

---

## 🚀 Start HERE (Next 30 Minutes)

### Option 1: Use the Swarm to Generate Tests (RECOMMENDED)
Let the agents do the work for you!

```bash
# Spawn test generation swarm
claude-code

# Then in Claude:
"Generate comprehensive tests for src/core/constants.py, src/core/engine.py, and src/core/file_host_config.py. Aim for >80% coverage with pytest. Include happy paths, error cases, and edge cases."
```

### Option 2: Manual Test Creation (Traditional)

**Step 1: Create test structure**
```bash
mkdir -p tests/unit/{core,network,storage,processing}
```

**Step 2: Start with easiest module**
```bash
# Create first test file
cat > tests/unit/core/test_constants.py << 'EOF'
"""Tests for core constants."""
import pytest
from src.core.constants import *

class TestConstants:
    def test_constants_exist(self):
        """Verify critical constants are defined."""
        assert APP_NAME
        assert VERSION

    def test_constant_types(self):
        """Verify constant types."""
        assert isinstance(APP_NAME, str)
        assert isinstance(VERSION, str)
EOF
```

**Step 3: Run and verify**
```bash
pytest tests/unit/core/test_constants.py -v --cov=src.core.constants
```

---

## 📋 Prioritized Module List

Test in this order for fastest coverage gains:

### Week 1: Quick Wins (Target: 10% → 15%)
1. ✅ `src/core/constants.py` (87 lines) - Easiest
2. ✅ `src/utils/format_utils.py` (63 lines) - Pure functions
3. ✅ `src/utils/archive_utils.py` (49 lines) - Simple logic
4. ✅ `src/network/cookies.py` (85 lines) - Standard operations
5. ✅ `src/network/token_cache.py` (75 lines) - Caching logic

**Expected gain:** +359 lines (~1.6% coverage)

### Week 2-3: Core Business Logic (Target: 15% → 30%)
6. ✅ `src/core/engine.py` (371 lines) - **CRITICAL**
7. ✅ `src/core/file_host_config.py` (240 lines) - **CRITICAL**
8. ✅ `src/storage/database.py` (652 lines) - **CRITICAL**
9. ✅ `src/network/client.py` (177 lines) - **CRITICAL**

**Expected gain:** +1,440 lines (~6.5% coverage)

### Week 4-5: Processing & Workers (Target: 30% → 45%)
10. ✅ `src/processing/tasks.py` (222 lines)
11. ✅ `src/processing/rename_worker.py` (274 lines)
12. ✅ `src/processing/file_host_workers.py` (406 lines)
13. ✅ `src/network/file_host_client.py` (887 lines)

**Expected gain:** +1,789 lines (~8% coverage)

### Week 6-7: Storage & Queue (Target: 45% → 60%)
14. ✅ `src/storage/queue_manager.py` (694 lines)
15. ✅ `src/utils/logging.py` (258 lines)
16. ✅ `src/utils/logger.py` (177 lines)
17. ✅ `src/processing/upload_workers.py` (317 lines)

**Expected gain:** +1,446 lines (~6.5% coverage)

---

## 🤖 Using Swarm for Test Generation

### Single Module
```python
# In Claude Code:
"Generate pytest tests for src/core/engine.py with >80% coverage.
Include:
- Initialization tests
- State transition tests
- Error handling tests
- Edge cases
- Mocking for external dependencies"
```

### Batch Generation
```python
# In Claude Code:
"Generate comprehensive test suite for these modules:
1. src/core/engine.py
2. src/core/file_host_config.py
3. src/storage/database.py

Requirements:
- >80% coverage per module
- pytest with fixtures
- Mock external dependencies
- Follow AAA pattern
- Include integration tests where needed"
```

### Full Package
```python
# In Claude Code:
"Generate complete test coverage for src/network/ package.
- All modules in the package
- Unit tests for each module
- Integration tests for workflows
- >80% coverage target
- Mock HTTP requests with 'responses' library"
```

---

## 📊 Track Your Progress

### After Each Test File
```bash
# Run tests
pytest tests/unit/core/test_constants.py -v

# Check coverage
pytest --cov=src.core.constants --cov-report=term

# See what's missing
pytest --cov=src.core.constants --cov-report=term-missing
```

### Overall Progress
```bash
# Full coverage report
pytest --cov=src --cov-report=html

# View in browser
explorer.exe htmlcov/index.html  # WSL
```

### Set a Goal
```bash
# Update pytest.ini to require minimum coverage
# Start low, increase gradually

# Week 1: Require 10%
fail-under = 10

# Week 3: Require 30%
fail-under = 30

# Week 8: Require 80%
fail-under = 80
```

---

## 💡 Pro Tips

### 1. Use Test Templates
```python
# Save as tests/templates/unit_test_template.py
"""Tests for {module_name}."""
import pytest
from unittest.mock import Mock, patch
from src.{module_path} import *

class Test{ClassName}:
    @pytest.fixture
    def setup(self):
        """Setup test fixtures."""
        pass

    def test_initialization(self, setup):
        """Test object initialization."""
        pass

    def test_happy_path(self, setup):
        """Test normal operation."""
        pass

    def test_error_handling(self, setup):
        """Test error cases."""
        pass
```

### 2. Test in Small Batches
Don't try to test everything at once:
- ✅ One module per day
- ✅ Run tests after each function
- ✅ Commit working tests immediately
- ✅ Celebrate small wins!

### 3. Focus on Critical Paths
Not all code is equally important:
- **HIGH:** Data integrity, network operations, file operations
- **MEDIUM:** Business logic, validation, formatting
- **LOW:** GUI rendering, logging, constants

### 4. Use Coverage to Guide You
```bash
# Find least-covered modules
coverage report --sort=cover | head -20

# Focus on files with 0% coverage first
```

---

## 🎯 30-Day Challenge

### Week 1: Foundation (5% → 15%)
- Day 1-2: Set up test structure, test constants
- Day 3-4: Test utils (format, archive)
- Day 5-7: Test network basics (cookies, cache)

### Week 2: Core (15% → 30%)
- Day 8-10: Test core.engine
- Day 11-12: Test core.file_host_config
- Day 13-14: Test storage.database (partial)

### Week 3: Storage & Network (30% → 45%)
- Day 15-17: Complete storage.database tests
- Day 18-19: Test network.client
- Day 20-21: Test network.file_host_client

### Week 4: Processing (45% → 60%)
- Day 22-24: Test processing.tasks & workers
- Day 25-26: Test processing.hooks_executor
- Day 27-28: Test processing coordinators

**Result:** 60% coverage in 4 weeks!

---

## ⚠️ Common Pitfalls

### 1. Don't Test GUI Rendering
❌ Bad: Testing if buttons appear
✅ Good: Testing button click handlers

### 2. Don't Write Fragile Tests
❌ Bad: `assert result == "Uploaded 5 files at 2025-11-13 10:30:15"`
✅ Good: `assert "Uploaded 5 files" in result`

### 3. Don't Skip Error Cases
❌ Bad: Only test happy paths
✅ Good: Test errors, exceptions, edge cases

### 4. Don't Mock Everything
❌ Bad: Mock so much nothing real is tested
✅ Good: Mock I/O, network, disk - test logic

---

## 🚀 TAKE ACTION NOW

### Your First Command (Copy & Paste):
```bash
# Create test structure
cd /mnt/h/cursor/imxup
mkdir -p tests/unit/{core,network,storage,processing}

# Create first test
cat > tests/unit/core/test_constants.py << 'EOF'
"""Tests for core constants."""
import pytest
from src.core.constants import *

def test_app_name_defined():
    """Test APP_NAME constant exists."""
    assert APP_NAME

def test_version_defined():
    """Test VERSION constant exists."""
    assert VERSION
EOF

# Run it
pytest tests/unit/core/test_constants.py -v

# Check coverage
pytest --cov=src.core.constants --cov-report=term
```

### Next Steps:
1. ✅ Run the command above
2. ✅ See tests pass
3. ✅ Check coverage increase
4. ✅ Move to next module
5. ✅ Repeat!

---

## 📚 Resources Created for You

1. **Detailed Roadmap:** `/docs/COVERAGE_ROADMAP.md` - Complete 12-week plan
2. **Test Reports:** `/swarm/results/TEST_REPORT.md` - Current test status
3. **This Guide:** `/COVERAGE_QUICKSTART.md` - You are here!

---

## 🎉 Celebrate Milestones

- ✅ 10% - Coffee break! ☕
- ✅ 25% - You're getting serious! 🎯
- ✅ 50% - Halfway there! 🎊
- ✅ 75% - Almost done! 🚀
- ✅ 80% - SUCCESS! 🎉

---

**Remember:** You don't have to do this alone. Use the swarm to generate tests automatically!

**Start NOW:** Copy the first command above and run it. You'll have your first test passing in 60 seconds!
