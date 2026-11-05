"""Tests for harness config loader and validator."""

import os
import pytest
from pathlib import Path
from harness.config import load_config, identity_capsule, validate_config, get_config_path

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_example_config_loads_with_allow_placeholders():
    """Verify example.toml is valid and loads when allow_placeholders is True."""
    example_path = REPO_ROOT / "config" / "example.toml"
    assert example_path.exists()
    old_env = os.environ.get("JOBSEARCH_CONFIG")
    try:
        os.environ["JOBSEARCH_CONFIG"] = str(example_path)
        cfg = load_config(allow_placeholders=True)
        assert cfg["min_ctc_lpa"] == 22
        assert "target_roles" in cfg

        # When allow_placeholders is False, it must raise ValueError
        with pytest.raises(ValueError, match="contains unconfigured placeholder"):
            load_config(allow_placeholders=False)
    finally:
        if old_env is not None:
            os.environ["JOBSEARCH_CONFIG"] = old_env
        else:
            os.environ.pop("JOBSEARCH_CONFIG", None)


def test_config_missing_required_key(tmp_path):
    """Verify validation raises ValueError on missing keys."""
    bad_toml = tmp_path / "missing_key.toml"
    bad_toml.write_text("""
name = "Test User"
email = "test@example.org"
# missing resume_url, min_ctc_lpa
""")
    old_env = os.environ.get("JOBSEARCH_CONFIG")
    try:
        os.environ["JOBSEARCH_CONFIG"] = str(bad_toml)
        with pytest.raises(ValueError, match="Missing required config key"):
            load_config()
    finally:
        if old_env is not None:
            os.environ["JOBSEARCH_CONFIG"] = old_env
        else:
            os.environ.pop("JOBSEARCH_CONFIG", None)


def test_config_bad_type(tmp_path):
    """Verify validation raises TypeError on wrong data types."""
    bad_toml = tmp_path / "bad_type.toml"
    bad_toml.write_text("""
name = "Test User"
email = "test@user.org"
resume_url = "https://user.org/resume"
min_ctc_lpa = "twenty-two"
target_roles = ["SDE-2"]
required_stack = ["Java"]
""")
    old_env = os.environ.get("JOBSEARCH_CONFIG")
    try:
        os.environ["JOBSEARCH_CONFIG"] = str(bad_toml)
        with pytest.raises(TypeError, match="min_ctc_lpa must be numeric"):
            load_config()
    finally:
        if old_env is not None:
            os.environ["JOBSEARCH_CONFIG"] = old_env
        else:
            os.environ.pop("JOBSEARCH_CONFIG", None)


def test_identity_capsule_structure():
    """Verify identity_capsule returns full dictionary structure."""
    capsule = identity_capsule(allow_placeholders=True)
    expected_keys = [
        "candidate_name", "email_primary", "resume_url", "forbidden_links",
        "notice_period", "total_experience", "target_roles", "min_ctc_lpa",
        "required_stack", "excluded_stack", "screening_answers", "caps"
    ]
    for k in expected_keys:
        assert k in capsule, f"Missing key '{k}' in identity capsule"
