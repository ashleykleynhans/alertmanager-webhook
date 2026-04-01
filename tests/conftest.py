"""Shared test fixtures and configuration for webhook tests."""
import builtins
import copy
import sys
from typing import Any

import pytest

from helpers import TEST_CONFIG, config_open, real_open

# Ensure clean import of webhook module with mocked config
if 'webhook' in sys.modules:
    del sys.modules['webhook']
builtins.open = config_open

import webhook  # noqa: E402

builtins.open = real_open
webhook.config = copy.deepcopy(TEST_CONFIG)


@pytest.fixture(autouse=True)
def _reset_config() -> None:
    """Reset webhook config before each test."""
    webhook.config = copy.deepcopy(TEST_CONFIG)


@pytest.fixture
def client() -> Any:
    """Provide a Flask test client."""
    webhook.app.config['TESTING'] = True
    with webhook.app.test_client() as c:
        yield c
