"""Tests for `kb init` scaffold behavior across tiers."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from kb_cli.cli import cli
from kb_cli.init import REQUIRED_WIKI_FOLDERS, RUNTIME_FOLDERS, scaffold


def _assert_structure(root: Path) -> None:
    assert (root / ".kb" / "schema.yaml").is_file()
    assert (root / ".kb" / "policy.yaml").is_file()
    assert (root / ".kb" / "tier.yaml").is_file()
    assert (root / ".kb" / "trust-store.yaml").is_file()
    assert (root / "wiki" / "index.md").is_file()
    assert (root / "wiki" / "log.md").is_file()
    for folder in REQUIRED_WIKI_FOLDERS:
        assert (root / "wiki" / folder / "README.md").is_file()
    for folder in RUNTIME_FOLDERS:
        assert (root / folder).is_dir()


def test_scaffold_individual_tier(tmp_path: Path) -> None:
    scaffold(
        root=tmp_path / "kb",
        tier="individual",
        publisher_id="did:web:example.invalid",
    )
    root = tmp_path / "kb"
    _assert_structure(root)

    policy = yaml.safe_load((root / ".kb" / "policy.yaml").read_text())
    assert policy["tier"] == "individual"
    assert policy["trust"]["model"] == "tofu"
    assert policy["publisher"]["distiller_mode"] == "manual"


def test_scaffold_team_tier(tmp_path: Path) -> None:
    scaffold(root=tmp_path / "kb", tier="team", publisher_id="did:web:team.example")
    policy = yaml.safe_load((tmp_path / "kb" / ".kb" / "policy.yaml").read_text())
    assert policy["tier"] == "team"
    assert policy["publisher"]["human_review"]["required"] is True
    assert policy["publisher"]["distiller_mode"] == "single-model"


def test_scaffold_enterprise_tier(tmp_path: Path) -> None:
    scaffold(
        root=tmp_path / "kb",
        tier="enterprise",
        publisher_id="did:web:bank.example",
    )
    policy = yaml.safe_load((tmp_path / "kb" / ".kb" / "policy.yaml").read_text())
    assert policy["tier"] == "enterprise"
    assert policy["trust"]["model"] == "allowlist"
    assert policy["publisher"]["human_review"]["min_reviewers"] == 2
    assert policy["publisher"]["distiller_mode"] == "dual-model"


def test_scaffold_generates_keypair(tmp_path: Path) -> None:
    scaffold(root=tmp_path / "kb", tier="individual", publisher_id="did:web:x.example")
    keys_dir = tmp_path / "kb" / ".kb" / "keys"
    pub_keys = list(keys_dir.glob("*.pub"))
    priv_keys = list(keys_dir.glob("*.priv"))
    assert len(pub_keys) == 1
    assert len(priv_keys) == 1
    pub_doc = yaml.safe_load(pub_keys[0].read_text())
    assert pub_doc["algorithm"] == "ed25519"
    assert len(pub_doc["public_key_hex"]) == 64
    assert priv_keys[0].stat().st_mode & 0o777 == 0o600


def test_scaffold_no_keygen_skips_keys(tmp_path: Path) -> None:
    scaffold(
        root=tmp_path / "kb",
        tier="individual",
        publisher_id="did:web:x.example",
        generate_keys=False,
    )
    keys_dir = tmp_path / "kb" / ".kb" / "keys"
    assert not keys_dir.exists() or not any(keys_dir.iterdir())


def test_scaffold_rejects_existing_kb_without_force(tmp_path: Path) -> None:
    scaffold(root=tmp_path / "kb", tier="individual", publisher_id="did:web:x.example")
    with pytest.raises(Exception) as exc:
        scaffold(root=tmp_path / "kb", tier="individual", publisher_id="did:web:y.example")
    assert "already contains a KB" in str(exc.value)


def test_scaffold_force_overwrites(tmp_path: Path) -> None:
    scaffold(root=tmp_path / "kb", tier="individual", publisher_id="did:web:x.example")
    scaffold(
        root=tmp_path / "kb",
        tier="enterprise",
        publisher_id="did:web:y.example",
        force=True,
    )
    tier_doc = yaml.safe_load((tmp_path / "kb" / ".kb" / "tier.yaml").read_text())
    assert tier_doc["tier"] == "enterprise"
    assert tier_doc["publisher_id"] == "did:web:y.example"


def test_init_command_via_cli(tmp_path: Path) -> None:
    runner = CliRunner()
    target = tmp_path / "my-kb"
    result = runner.invoke(
        cli,
        [
            "init",
            str(target),
            "--tier",
            "team",
            "--publisher-id",
            "did:web:team.example",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "team-tier KB" in result.output
    _assert_structure(target)
