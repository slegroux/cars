"""Config loader — YAML → Pydantic v2 models."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, field_validator, model_validator


class BudgetConfig(BaseModel):
    min: float = 5000
    max: float = 12000


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
    """Load config from YAML file. Defaults to ./config.yaml."""
    if path is None:
        path = Path("config.yaml")
    with open(path) as f:
        data: dict[str, Any] = yaml.safe_load(f) or {}
    return Config(**data)


def resolved_vault_path(config: Config) -> Path:
    """Return the resolved vault export path, env var takes priority."""
    raw = os.environ.get("CARFINDER_VAULT_PATH", config.export.vault_path)
    return Path(os.path.expanduser(raw))
