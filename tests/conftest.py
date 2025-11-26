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
