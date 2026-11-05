"""Configuration loader and validator for Job Harness and Identity Capsule."""

import os
from pathlib import Path
from typing import Any, Dict

try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib  # type: ignore
    except ImportError:
        tomllib = None  # type: ignore

REPO_ROOT = Path(__file__).resolve().parent.parent

PLACEHOLDER_TOKENS = ["[YOUR_NAME]", "[YOUR_EMAIL]", "[YOUR_PHONE]", "[YOUR_LOCATION]", "example.com"]


def get_config_path() -> Path:
    override = os.environ.get("JOBSEARCH_CONFIG")
    if override:
        return Path(override)
    local_path = REPO_ROOT / "config" / "local.toml"
    if local_path.exists():
        return local_path
    return REPO_ROOT / "config" / "example.toml"


def validate_config(cfg: Dict[str, Any], allow_placeholders: bool = False) -> None:
    required_keys = ["name", "email", "resume_url", "min_ctc_lpa", "target_roles", "required_stack"]
    for k in required_keys:
        if k not in cfg:
            raise ValueError(f"Missing required config key: '{k}'")

    if not isinstance(cfg["min_ctc_lpa"], (int, float)):
        raise TypeError(f"min_ctc_lpa must be numeric, got {type(cfg['min_ctc_lpa'])}")

    if not isinstance(cfg["target_roles"], list):
        raise TypeError(f"target_roles must be a list, got {type(cfg['target_roles'])}")

    if not isinstance(cfg["required_stack"], list):
        raise TypeError(f"required_stack must be a list, got {type(cfg['required_stack'])}")

    if not allow_placeholders:
        for k in ["name", "email", "resume_url"]:
            val = str(cfg.get(k, ""))
            for token in PLACEHOLDER_TOKENS:
                if token in val:
                    raise ValueError(f"Config field '{k}' contains unconfigured placeholder '{token}'")


def load_config(allow_placeholders: bool = True) -> Dict[str, Any]:
    config_path = get_config_path()
    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    if tomllib is None:
        raise RuntimeError("tomllib/tomli is required to parse TOML configuration.")

    with open(config_path, "rb") as f:
        data = tomllib.load(f)

    validate_config(data, allow_placeholders=allow_placeholders)
    return data


def identity_capsule(allow_placeholders: bool = True) -> Dict[str, Any]:
    cfg = load_config(allow_placeholders=allow_placeholders)
    caps = cfg.get("caps", {})
    screening = cfg.get("screening", {})

    return {
        "candidate_name": cfg.get("name", ""),
        "email_primary": cfg.get("email", ""),
        "phone": cfg.get("phone", ""),
        "resume_url": cfg.get("resume_url", ""),
        "forbidden_links": cfg.get("banned_links", ["shorturl.at"]),
        "bullets": cfg.get("bullets", [
            "Built and operated backend services in production (set your own bullets in config/local.toml)"
        ]),
        "notice_period": cfg.get("notice_period", "30 days"),
        "total_experience": cfg.get("total_experience", "3 years"),
        "current_location": cfg.get("location", ""),
        "relocation_preference": cfg.get("relocation_preference", ""),
        "target_roles": cfg.get("target_roles", []),
        "min_ctc_lpa": cfg.get("min_ctc_lpa", 22),
        "expected_ctc": cfg.get("expected_ctc", 30),
        "required_stack": cfg.get("required_stack", []),
        "excluded_stack": cfg.get("excluded_stack", []),
        "pitch_paragraph": cfg.get("pitch", ""),
        "screening_answers": screening,
        "caps": caps,
    }
