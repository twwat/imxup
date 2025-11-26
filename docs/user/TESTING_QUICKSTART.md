# Quick Testing Setup (No venv required)

## Install pytest via apt (System packages)

```bash
# Install python testing tools
sudo apt update
sudo apt install python3-pytest python3-pytest-cov

# Verify installation
pytest --version
```

## Run Tests

```bash
# Navigate to project
cd /mnt/h/cursor/imxup

# Run all tests
pytest tests/

# Run with coverage (if pytest-cov installed)
pytest --cov=src tests/

# Run specific test files
pytest tests/unit/test_config_validation.py
pytest tests/integration/test_swarm_initialization.py
```

## If you want the full test suite with all dependencies

You need to install python3-venv first:

```bash
# Install venv support
sudo apt install python3.12-venv python3-full

# Then create venv
python3 -m venv ~/imxup-venv
source ~/imxup-venv/bin/activate
pip install -r tests/requirements.txt
```

## Alternative: Use pipx for isolated installs

```bash
# Install pipx
sudo apt install pipx

# Install pytest with pipx
pipx install pytest
pipx inject pytest pytest-cov pytest-mock

# Run tests
cd /mnt/h/cursor/imxup
pytest tests/
```
