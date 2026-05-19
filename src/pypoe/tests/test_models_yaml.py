"""Tests for ``pypoe.core.models``'s YAML loader.

Validates the YAML→fallback precedence by pointing
``PYPOE_MODELS_CONFIG`` at a tmp file and re-importing the module.
"""

from __future__ import annotations

import importlib
import sys

import pytest

yaml = pytest.importorskip("yaml")


def _reimport(monkeypatch, models_path):
    """Re-import pypoe.core.models with PYPOE_MODELS_CONFIG pointed at path."""
    monkeypatch.setenv("PYPOE_MODELS_CONFIG", str(models_path))
    # Drop the cached module so the loader runs again with the new env.
    sys.modules.pop("pypoe.core.models", None)
    return importlib.import_module("pypoe.core.models")


def test_yaml_overrides_hardcoded(tmp_path, monkeypatch):
    cfg = tmp_path / "models.yaml"
    cfg.write_text(yaml.safe_dump({
        "default": "Test-Bot-1",
        "chat_models": ["Test-Bot-1", "Test-Bot-2"],
        "pricing_usd_per_1m_tokens": {
            "Test-Bot-1": {"prompt": 1.0, "completion": 2.0},
        },
    }))
    mod = _reimport(monkeypatch, cfg)
    assert mod.CHAT_MODELS == ["Test-Bot-1", "Test-Bot-2"]
    assert mod.DEFAULT_CHAT_MODEL == "Test-Bot-1"
    assert mod.MODEL_PRICING_USD_PER_1M_TOKENS["Test-Bot-1"]["prompt"] == 1.0


def test_missing_file_uses_fallbacks(tmp_path, monkeypatch):
    """If models.yaml doesn't exist, the hardcoded fallbacks ship."""
    mod = _reimport(monkeypatch, tmp_path / "does_not_exist.yaml")
    # Hardcoded snapshot includes Claude-Sonnet-4.6 as default.
    assert mod.DEFAULT_CHAT_MODEL == "Claude-Sonnet-4.6"
    assert "Claude-Opus-4.7" in mod.CHAT_MODELS


def test_malformed_yaml_uses_fallbacks(tmp_path, monkeypatch):
    """Parse errors fall back rather than crashing import."""
    cfg = tmp_path / "models.yaml"
    cfg.write_text("not: valid: yaml::: at all")
    mod = _reimport(monkeypatch, cfg)
    assert mod.DEFAULT_CHAT_MODEL == "Claude-Sonnet-4.6"


def test_partial_yaml_fills_in_missing_keys(tmp_path, monkeypatch):
    """A YAML with only `chat_models` keeps fallback default + pricing."""
    cfg = tmp_path / "models.yaml"
    cfg.write_text(yaml.safe_dump({"chat_models": ["Only-Bot"]}))
    mod = _reimport(monkeypatch, cfg)
    assert mod.CHAT_MODELS == ["Only-Bot"]
    assert mod.DEFAULT_CHAT_MODEL == "Claude-Sonnet-4.6"  # fallback
    assert "Claude-Opus-4.7" in mod.MODEL_PRICING_USD_PER_1M_TOKENS  # fallback


@pytest.fixture(autouse=True)
def _reset_models_module_after(monkeypatch):
    """Restore the production-config-loaded module after each test."""
    yield
    monkeypatch.delenv("PYPOE_MODELS_CONFIG", raising=False)
    sys.modules.pop("pypoe.core.models", None)
    importlib.import_module("pypoe.core.models")
