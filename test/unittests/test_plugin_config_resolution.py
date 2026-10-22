# Licensed under the Apache License, Version 2.0
"""ModelContainer/MultiModelContainer resolve plugin config from mycroft.conf.

Regression test: with no explicit config, the containers must pass the
plugin's own section from Configuration() to the STT class — matching
OVOSSTTFactory — instead of an empty dict (which silently loads the
plugin's default model regardless of the mounted mycroft.conf).
"""
from unittest.mock import MagicMock, patch

import pytest


PLUGIN = "fake-stt-plugin"
CONF = {"stt": {PLUGIN: {"model": "my/custom-model"}}}


def _plugin_cls(captured):
    def factory(config=None, **kwargs):
        captured["config"] = config
        engine = MagicMock()
        engine.bind = MagicMock()
        return engine
    return factory


def test_model_container_reads_mycroft_conf():
    captured = {}
    with patch("ovos_stt_http_server.Configuration", return_value=CONF), \
         patch("ovos_stt_http_server.load_stt_plugin", return_value=_plugin_cls(captured)):
        from ovos_stt_http_server import ModelContainer
        ModelContainer(PLUGIN)
    assert captured["config"] == {"model": "my/custom-model"}


def test_model_container_explicit_config_wins():
    captured = {}
    with patch("ovos_stt_http_server.Configuration", return_value=CONF), \
         patch("ovos_stt_http_server.load_stt_plugin", return_value=_plugin_cls(captured)):
        from ovos_stt_http_server import ModelContainer
        ModelContainer(PLUGIN, config={"model": "override"})
    assert captured["config"] == {"model": "override"}


def test_multi_model_container_reads_mycroft_conf():
    captured = {}
    with patch("ovos_stt_http_server.Configuration", return_value=CONF), \
         patch("ovos_stt_http_server.load_stt_plugin", return_value=_plugin_cls(captured)):
        from ovos_stt_http_server import MultiModelContainer
        mc = MultiModelContainer(PLUGIN)
        mc.load_engine("en")
    assert captured["config"]["model"] == "my/custom-model"


def test_missing_section_defaults_to_empty():
    captured = {}
    with patch("ovos_stt_http_server.Configuration", return_value={}), \
         patch("ovos_stt_http_server.load_stt_plugin", return_value=_plugin_cls(captured)):
        from ovos_stt_http_server import ModelContainer
        ModelContainer(PLUGIN)
    assert captured["config"] == {}
