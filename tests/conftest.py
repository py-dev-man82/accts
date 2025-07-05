import pytest
import os
import sys

# Ensure project root is in sys.path so config can be imported
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, os.pardir))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import config
from secure_db import SecureDB

@pytest.fixture(scope="session")
def db(tmp_path_factory):
    # Create a temporary database file for testing
    path = tmp_path_factory.mktemp("data") / "test_db.json"
    # Initialize SecureDB in test mode (encryption disabled)
    test_db = SecureDB(str(path))
    yield test_db
    # No teardown necessary; temporary directories are handled by pytest
