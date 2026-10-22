from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def empty_transformer_config():
    """Keep tests hermetic: never pick up transformer sections from the
    machine-local mycroft.conf when containers initialize their pipelines."""
    with patch("ovos_stt_http_server.Configuration", return_value={}):
        yield
