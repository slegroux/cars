"""Config loader — YAML → Pydantic v2 models."""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, field_validator, model_validator


class BudgetConfig(BaseModel):
    min: float = 5000
    max: float = 12000

    @model_validator(mode="after")
    def _validate_range(self) -> "BudgetConfig":
        if self.min > self.max:
            raise ValueError(
                f"budget.min ({self.min}) must be <= budget.max ({self.max})"
            )
        return self


class MileageConfig(BaseModel):
    max: int = 100000
    sweet_spot: list[int] = [50000, 80000]


class TransmissionConfig(BaseModel):
    exclude_manual: bool = True


class SourcesConfig(BaseModel):
    craigslist: bool = True
    carmax: bool = False
    carscom: bool = False
    kbb: bool = False
    facebook: bool = False


class WeightsConfig(BaseModel):
    reliability: float = 0.22
    price_value: float = 0.18
    mileage: float = 0.16
    size_class: float = 0.12
    insurance_risk: float = 0.10
    seller_type: float = 0.05
    roof_rack: float = 0.06
    mpg: float = 0.04
    drivetrain: float = 0.03
    parking_footprint: float = 0.02
    title_status: float = 0.02

    @model_validator(mode="after")
    def _validate_bounds(self) -> "WeightsConfig":
        for fname in WeightsConfig.model_fields:
            val = getattr(self, fname)
            if not 0.0 <= val <= 1.0:
                raise ValueError(
                    f"weight {fname!r}={val} must be between 0 and 1"
                )
        return self


class ExportConfig(BaseModel):
    vault_path: str = "~/Obsidian/PersonalVault/wiki/cars"
    photo_thumbnails: int = 3


class RateLimitConfig(BaseModel):
    min_delay_seconds: float = 2
    max_delay_seconds: float = 5


class RetryConfig(BaseModel):
    max_retries: int = 3
    backoff_base: float = 2
    retryable_status: list[int] = [429, 503]


class Config(BaseModel):
    zip: str = "90405"
    radius_miles: int = 25
    budget: BudgetConfig = BudgetConfig()
    mileage: MileageConfig = MileageConfig()
    transmission: TransmissionConfig = TransmissionConfig()
    sources: SourcesConfig = SourcesConfig()
    carmax_include_transfer: bool = True
    carmax_max_transfer_miles: int = 200
    weights: WeightsConfig = WeightsConfig()
    export: ExportConfig = ExportConfig()
    rate_limit: RateLimitConfig = RateLimitConfig()
    retry: RetryConfig = RetryConfig()

    @field_validator("zip")
    @classmethod
    def _validate_zip(cls, v: str) -> str:
        s = str(v).strip()
        if not re.fullmatch(r"\d{5}", s):
            raise ValueError(f"zip must be a 5-digit US ZIP code, got {v!r}")
        return s

    @field_validator("radius_miles")
    @classmethod
    def _validate_radius(cls, v: int) -> int:
        if v <= 0:
            raise ValueError(f"radius_miles must be a positive integer, got {v}")
        return v

    @model_validator(mode="after")
    def validate_weights_sum(self) -> "Config":
        total = sum(
            getattr(self.weights, field)
            for field in WeightsConfig.model_fields
        )
        if abs(total - 1.0) > 0.001:
            raise ValueError(
                f"weights must sum to 1.0 (±0.001), got {total:.4f}"
            )
        return self


def load_config(path: Path | None = None) -> Config:
    """Load config from YAML file. Defaults to ./config.yaml.

    Raises a clear FileNotFoundError if the file is missing and a ValueError
    if it is not valid YAML, instead of leaking a raw traceback to the user.
    """
    if path is None:
        path = Path("config.yaml")
    try:
        with open(path) as f:
            data: dict[str, Any] = yaml.safe_load(f) or {}
    except FileNotFoundError as e:
        raise FileNotFoundError(
            f"Config file not found: {path}. Copy the bundled config.yaml to the "
            f"repo root or pass an explicit --config path."
        ) from e
    except yaml.YAMLError as e:
        raise ValueError(f"Config file {path} is not valid YAML: {e}") from e
    return Config(**data)


def resolved_vault_path(config: Config) -> Path:
    """Return the resolved vault export path, env var takes priority."""
    raw = os.environ.get("CARFINDER_VAULT_PATH", config.export.vault_path)
    return Path(os.path.expanduser(raw))
