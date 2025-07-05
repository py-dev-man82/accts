import pytest
import config
from secure_db import SecureDB

@pytest.fixture(scope="session")
def db(tmp_path_factory):
    # Create a temporary database file for testing
    path = tmp_path_factory.mktemp("data") / "test_db.json"
    # Initialize SecureDB in test mode (encryption disabled)
    test_db = SecureDB(str(path))
    yield test_db
    # No teardown necessary; temp directories are auto-removed
