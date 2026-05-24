"""Tests for config.py."""
from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from carfinder.config import Config, load_config, resolved_vault_path


CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"


def test_load_default_config(tmp_path):
    """load_config reads config.yaml and returns a Config."""
    config = load_config(CONFIG_PATH)
    assert config.zip == "90405"
    assert config.budget.min == 5000
    assert config.budget.max == 12000
    assert config.transmission.exclude_manual is True


def test_weights_sum_to_one():
    """Weights in the default config.yaml must sum to 1.0."""
    config = load_config(CONFIG_PATH)
    from carfinder.config import WeightsConfig
    total = sum(
        getattr(config.weights, f) for f in WeightsConfig.model_fields
    )
    assert abs(total - 1.0) <= 0.001, f"weights sum to {total}"


def test_env_var_overrides_vault_path(monkeypatch, tmp_path):
    """CARFINDER_VAULT_PATH env var overrides config vault_path."""
    override = str(tmp_path / "my_vault")
    monkeypatch.setenv("CARFINDER_VAULT_PATH", override)
    config = load_config(CONFIG_PATH)
    result = resolved_vault_path(config)
    assert result == Path(override)


def test_resolved_vault_path_expands_tilde():
    """resolved_vault_path expands ~ when no env var is set."""
    if "CARFINDER_VAULT_PATH" in os.environ:
        pytest.skip("CARFINDER_VAULT_PATH is set in environment")
    config = load_config(CONFIG_PATH)
    result = resolved_vault_path(config)
    assert "~" not in str(result)
    assert str(result).startswith("/")


def test_bad_weights_raise_value_error(tmp_path):
    """load_config raises ValueError if weights don't sum to 1.0."""
    bad_config = {
        "zip": "90405",
        "weights": {
            "reliability": 0.30,  # inflated
            "price_value": 0.20,
            "mileage": 0.16,
            "size_class": 0.12,
            "insurance_risk": 0.08,
            "mpg": 0.08,
            "parking_footprint": 0.06,
            "drivetrain": 0.02,
            "roof_rack": 0.03,
            "title_status": 0.03,
        },
    }
    cfg_file = tmp_path / "bad_config.yaml"
    cfg_file.write_text(yaml.dump(bad_config))
    with pytest.raises(ValueError, match="weights must sum to 1.0"):
        load_config(cfg_file)
