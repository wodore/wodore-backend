import os
from pathlib import Path


def pytest_configure(config):
    """Load test environment variables before Django is configured."""
    env_file = Path(__file__).parent.parent / ".env.test"
    if env_file.exists():
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    os.environ.setdefault(key.strip(), value.strip().strip("\"'"))
