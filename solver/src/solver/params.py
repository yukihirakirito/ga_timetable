"""Đọc `schedule_runs.params` (xem contracts/run_params.schema.json) thành GAParams + Weights."""

from __future__ import annotations

import json
from dataclasses import fields

from jsonschema import Draft202012Validator

from .evaluate import Weights
from .ga import GAParams
from .problem import REPO_ROOT

SCHEMA_PATH = REPO_ROOT / "contracts" / "run_params.schema.json"


class ParamsError(ValueError):
    def __init__(self, errors: list[str]):
        super().__init__("params không hợp lệ:\n  " + "\n  ".join(errors))
        self.errors = errors


def _validator() -> Draft202012Validator:
    return Draft202012Validator(json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))


def parse_params(raw: dict | None) -> tuple[GAParams, Weights]:
    raw = raw or {}
    errors = [f"/{'/'.join(map(str, e.absolute_path))}: {e.message}"
              for e in sorted(_validator().iter_errors(raw), key=lambda e: list(e.absolute_path))]
    if errors:
        raise ParamsError(errors)

    ga = GAParams(**raw.get("ga", {}))
    weights = Weights(**raw.get("weights", {}))
    if ga.elite >= ga.pop_size:
        errors.append(f"/ga: elite ({ga.elite}) phải nhỏ hơn pop_size ({ga.pop_size})")
    if ga.tournament_k > ga.pop_size:
        errors.append(f"/ga: tournament_k ({ga.tournament_k}) không được lớn hơn pop_size ({ga.pop_size})")
    if errors:
        raise ParamsError(errors)
    return ga, weights


def params_to_dict(ga: GAParams, weights: Weights) -> dict:
    """Dạng đầy đủ (đã điền mặc định), khớp schema."""
    return {"ga": {f.name: getattr(ga, f.name) for f in fields(ga)}, "weights": weights.to_dict()}
