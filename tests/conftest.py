"""
Pytest configuration and fixtures for imxup swarm testing.
Provides shared fixtures, test utilities, and environment setup.
"""

import pytest
import json
import tempfile
import shutil
from pathlib import Path
from typing import Dict, Any, List
import sqlite3
from datetime import datetime
import os
import gc


@pytest.fixture(autouse=True)
def mock_qmessagebox_globally(monkeypatch):
    """
    CRITICAL: Mock QMessageBox to prevent modal dialogs from blocking test teardown.

    Many dialogs (e.g., FileHostConfigDialog) show confirmation messages in closeEvent,
    which blocks pytest-qt's internal _close_widgets() function during teardown.

    This fixture auto-returns Discard for all warning/question dialogs to prevent
    the test suite from hanging indefinitely.
    """
    try:
        from PyQt6.QtWidgets import QMessageBox

        # Create mock that returns Discard (to skip saving) or Yes/Ok (to proceed)
        def mock_warning(*args, **kwargs):
            return QMessageBox.StandardButton.Discard

        def mock_question(*args, **kwargs):
            return QMessageBox.StandardButton.Yes

        def mock_information(*args, **kwargs):
            return QMessageBox.StandardButton.Ok

        def mock_critical(*args, **kwargs):
            return QMessageBox.StandardButton.Ok

        # Patch all static dialog methods
        monkeypatch.setattr(QMessageBox, 'warning', mock_warning)
        monkeypatch.setattr(QMessageBox, 'question', mock_question)
        monkeypatch.setattr(QMessageBox, 'information', mock_information)
        monkeypatch.setattr(QMessageBox, 'critical', mock_critical)
    except ImportError:
        # PyQt6 not available in this test environment
        pass

    yield


@pytest.fixture(autouse=True)
def cleanup_qt_resources():
    """Comprehensive cleanup of Qt resources after each test to prevent hangs.

    This fixture addresses multiple resource leak sources:
    - QTimer instances (from ProportionalBar, dialogs, etc.)
    - QThread instances (workers)
    - Singleton instances (MetricsStore, IconManager, etc.)
    - Database connections
    - Pending deleteLater() calls
    - Signal connections
    """
    yield

    # Step 1: Stop ALL QTimers FIRST (critical for preventing hangs)
    try:
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtCore import QTimer, QThread

        app = QApplication.instance()
        if app is not None:
            # Process any pending events before cleanup
            app.processEvents()

            # Stop all QTimers (ProportionalBar animations, etc.)
            for timer in app.findChildren(QTimer):
                if timer.isActive():
                    timer.stop()

            # Process events again to let timers actually stop
            app.processEvents()
    except (ImportError, Exception):
        pass

    # Step 2: Stop and cleanup all QThreads
    try:
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtCore import QThread

        app = QApplication.instance()
        if app is not None:
            threads = app.findChildren(QThread)
            for thread in threads:
                if thread.isRunning():
                    # Call custom stop method if available
                    if hasattr(thread, 'stop') and callable(thread.stop):
                        try:
                            thread.stop()
                        except Exception:
                            pass

                    # Request thread to quit
                    thread.quit()

                    # Wait briefly (100ms max to avoid test suite hanging)
                    if not thread.wait(100):
                        # Force terminate immediately if not responsive
                        thread.terminate()
                        thread.wait(50)

            # Process events to let threads finish cleanup
            app.processEvents()
    except (ImportError, Exception):
        pass

    # Step 3: Close all database connections
    try:
        import sqlite3
        # Close any open sqlite3 connections in the current thread
        # This is important for tests that create database connections
        gc.collect()  # Trigger garbage collection to close unreferenced connections
    except Exception:
        pass

    # Step 4: Reset singleton instances
    try:
        # Reset MetricsStore singleton
        from src.utils.metrics_store import MetricsStore
        if hasattr(MetricsStore, '_instance') and MetricsStore._instance is not None:
            instance = MetricsStore._instance
            try:
                instance.close()
            except Exception:
                pass
            MetricsStore._instance = None
    except (ImportError, Exception):
        pass

    try:
        # Reset IconManager global instance and cache
        import src.gui.icon_manager as icon_mgr_module
        if hasattr(icon_mgr_module, '_icon_manager') and icon_mgr_module._icon_manager is not None:
            icon_manager = icon_mgr_module._icon_manager
            try:
                # Clear the icon cache to release QIcon objects
                icon_manager.refresh_cache()
            except Exception:
                pass
            # Reset the global instance
            icon_mgr_module._icon_manager = None
    except (ImportError, Exception):
        pass

    try:
        # Reset any other singletons that might exist
        from src.core.file_host_config import FileHostConfigLoader
        if hasattr(FileHostConfigLoader, '_instance'):
            FileHostConfigLoader._instance = None
    except (ImportError, Exception):
        pass

    try:
        # Clear database schema initialization tracker to avoid state leakage
        from src.storage import database
        if hasattr(database, '_schema_initialized_dbs'):
            database._schema_initialized_dbs.clear()
    except (ImportError, Exception):
        pass

    # Step 5: Process ALL pending deleteLater() calls
    try:
        from PyQt6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is not None:
            # Send all deferred delete events
            app.sendPostedEvents(None, 0)  # 0 = QEvent.DeferredDelete

            # Process events multiple times to ensure all deleteLater() calls are processed
            for _ in range(5):
                app.processEvents()
    except (ImportError, Exception):
        pass

    # Step 6: Disconnect any lingering signal connections
    # (Qt should handle this automatically, but we'll force cleanup)
    try:
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtCore import QObject

        app = QApplication.instance()
        if app is not None:
            # Let Qt's internal cleanup handle disconnections
            app.processEvents()
    except (ImportError, Exception):
        pass

    # Step 7: Force garbage collection (multiple passes)
    gc.collect()
    gc.collect()  # Second pass to catch circular references
    gc.collect()  # Third pass to be absolutely sure

    # Step 8: Final event processing
    try:
        from PyQt6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is not None:
            app.processEvents()
    except (ImportError, Exception):
        pass

@pytest.fixture(scope="session")
def test_root():
    """Return the test root directory."""
    return Path(__file__).parent


@pytest.fixture(scope="session")
def project_root():
    """Return the project root directory."""
    return Path(__file__).parent.parent


@pytest.fixture(scope="session")
def swarm_root(project_root):
    """Return the swarm directory."""
    return project_root / "swarm"


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files."""
    tmp = tempfile.mkdtemp()
    yield Path(tmp)
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture
def temp_memory_db(temp_dir):
    """Create a temporary memory database for testing."""
    db_path = temp_dir / "test-memory.db"
    conn = sqlite3.connect(str(db_path))

    # Create tables
    conn.execute("""
        CREATE TABLE IF NOT EXISTS memory (
            key TEXT,
            value TEXT,
            namespace TEXT,
            timestamp INTEGER,
            PRIMARY KEY (key, namespace)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            task_id TEXT PRIMARY KEY,
            description TEXT,
            status TEXT,
            created_at INTEGER,
            completed_at INTEGER
        )
    """)
    conn.commit()

    yield conn

    conn.close()


@pytest.fixture
def sample_swarm_config():
    """Provide a sample swarm configuration."""
    return {
        "swarmId": "test-swarm-001",
        "objective": "init",
        "topology": "mesh",
        "strategy": "auto",
        "mode": "centralized",
        "maxAgents": 6,
        "timeout": 3600,
        "parallelExecution": True,
        "createdAt": "2025-11-13T00:00:00Z",
        "status": "initializing"
    }


@pytest.fixture
def sample_agent_instructions():
    """Provide sample agent instructions."""
    return {
        "researcher": {
            "objective": "Analyze project requirements",
            "tasks": [
                "Review documentation",
                "Analyze codebase",
                "Document findings"
            ],
            "hooks": [
                "npx claude-flow@alpha hooks pre-task --description 'research'",
                "npx claude-flow@alpha hooks post-task --task-id 'research-001'"
            ],
            "deliverables": "requirements-analysis.json"
        },
        "coder": {
            "objective": "Implement features",
            "tasks": [
                "Write code",
                "Add tests",
                "Document API"
            ],
            "hooks": [
                "npx claude-flow@alpha hooks pre-task --description 'coding'",
                "npx claude-flow@alpha hooks post-task --task-id 'coder-001'"
            ],
            "deliverables": "implementation.py"
        }
    }


@pytest.fixture
def sample_objective():
    """Provide a sample objective configuration."""
    return {
        "objective": "init",
        "description": "Initialize swarm coordination system",
        "analysisPhase": "specification",
        "requirements": [
            "Analyze requirements",
            "Design architecture",
            "Implement system"
        ],
        "detectedScope": "system-initialization",
        "priority": "high"
    }


@pytest.fixture
def mock_file_system(temp_dir):
    """Create a mock file system structure for testing."""
    # Create directory structure
    dirs = [
        "swarm/config",
        "swarm/memory",
        "swarm/results",
        "swarm/tasks",
        "swarm/architecture",
        "swarm/docs",
        "tests/unit",
        "tests/integration"
    ]

    for dir_path in dirs:
        (temp_dir / dir_path).mkdir(parents=True, exist_ok=True)

    return temp_dir


@pytest.fixture
def write_json_file(temp_dir):
    """Factory fixture to write JSON files."""
    def _write(rel_path: str, data: Dict[Any, Any]):
        file_path = temp_dir / rel_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, 'w') as f:
            json.dump(data, f, indent=2)
        return file_path
    return _write


@pytest.fixture
def read_json_file():
    """Factory fixture to read JSON files."""
    def _read(file_path: Path) -> Dict[Any, Any]:
        with open(file_path, 'r') as f:
            return json.load(f)
    return _read


@pytest.fixture
def mock_hooks_execution(monkeypatch):
    """Mock hook execution to avoid actual subprocess calls."""
    executed_hooks = []

    def mock_execute_hook(hook_cmd: str):
        executed_hooks.append(hook_cmd)
        return {
            "success": True,
            "task_id": f"task-{len(executed_hooks)}",
            "timestamp": datetime.now().isoformat()
        }

    return executed_hooks, mock_execute_hook


@pytest.fixture
def assert_coverage():
    """Utility to assert test coverage requirements."""
    def _assert(coverage_data: Dict[str, float], min_coverage: float = 0.80):
        for metric, value in coverage_data.items():
            assert value >= min_coverage, \
                f"{metric} coverage {value:.2%} is below threshold {min_coverage:.2%}"
    return _assert


@pytest.fixture
def create_test_task():
    """Factory to create test task objects."""
    def _create(task_id: str, description: str, status: str = "pending") -> Dict[str, Any]:
        return {
            "task_id": task_id,
            "description": description,
            "status": status,
            "created_at": datetime.now().isoformat(),
            "completed_at": None if status == "pending" else datetime.now().isoformat()
        }
    return _create


@pytest.fixture
def coordination_log():
    """Factory to create coordination log entries."""
    entries = []

    def _log(agent: str, action: str, details: Dict[str, Any]):
        entry = {
            "timestamp": datetime.now().isoformat(),
            "agent": agent,
            "action": action,
            "details": details
        }
        entries.append(entry)
        return entry

    return entries, _log


@pytest.fixture(autouse=True)
def reset_environment(monkeypatch):
    """Reset environment variables for each test."""
    # Save original env
    original_env = dict(os.environ)

    yield

    # Restore original env
    os.environ.clear()
    os.environ.update(original_env)


@pytest.fixture
def mock_claude_flow_client():
    """Mock Claude Flow MCP client."""
    class MockClaudeFlowClient:
        def __init__(self):
            self.calls = []
            self.memory = {}

        def swarm_init(self, topology: str, max_agents: int):
            self.calls.append(("swarm_init", topology, max_agents))
            return {"swarmId": "mock-swarm-001", "status": "initialized"}

        def agent_spawn(self, agent_type: str):
            self.calls.append(("agent_spawn", agent_type))
            return {"agentId": f"agent-{len(self.calls)}", "type": agent_type}

        def memory_store(self, key: str, value: Any, namespace: str = "default"):
            self.memory[f"{namespace}:{key}"] = value
            self.calls.append(("memory_store", key, namespace))
            return {"success": True}

        def memory_retrieve(self, key: str, namespace: str = "default"):
            self.calls.append(("memory_retrieve", key, namespace))
            return self.memory.get(f"{namespace}:{key}")

    return MockClaudeFlowClient()


# Test markers
def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "unit: Unit tests for individual components"
    )
    config.addinivalue_line(
        "markers", "integration: Integration tests for component interaction"
    )
    config.addinivalue_line(
        "markers", "e2e: End-to-end workflow tests"
    )
    config.addinivalue_line(
        "markers", "performance: Performance and benchmark tests"
    )
    config.addinivalue_line(
        "markers", "slow: Tests that take significant time"
    )


# Custom assertions
class AssertionHelpers:
    """Custom assertion helpers for tests."""

    @staticmethod
    def assert_valid_json_file(file_path: Path):
        """Assert file exists and contains valid JSON."""
        assert file_path.exists(), f"File does not exist: {file_path}"
        with open(file_path) as f:
            data = json.load(f)
        assert data is not None, "JSON file is empty or invalid"
        return data

    @staticmethod
    def assert_valid_swarm_config(config: Dict[str, Any]):
        """Assert swarm configuration is valid."""
        required_fields = ["swarmId", "objective", "topology", "maxAgents"]
        for field in required_fields:
            assert field in config, f"Missing required field: {field}"

        assert config["maxAgents"] > 0, "maxAgents must be positive"
        assert config["topology"] in ["mesh", "hierarchical", "ring", "star"], \
            f"Invalid topology: {config['topology']}"

    @staticmethod
    def assert_valid_agent_instructions(instructions: Dict[str, Any], agent_type: str):
        """Assert agent instructions are valid."""
        assert agent_type in instructions, f"Missing instructions for {agent_type}"
        agent_data = instructions[agent_type]

        required_fields = ["objective", "tasks", "hooks", "deliverables"]
        for field in required_fields:
            assert field in agent_data, \
                f"Missing required field '{field}' for {agent_type}"

        assert isinstance(agent_data["tasks"], list), "tasks must be a list"
        assert len(agent_data["tasks"]) > 0, "tasks list cannot be empty"


@pytest.fixture
def assert_helpers():
    """Provide assertion helpers."""
    return AssertionHelpers()
