from __future__ import annotations

from pathlib import Path

from ledgercore.cli import ExitCode, inspect_migration, recover_migration


def test_inspect_cli_error_has_stable_machine_fields(tmp_path: Path) -> None:
    response = inspect_migration(tmp_path / "missing.toml")

    assert response.ok is False
    assert response.exit_code == ExitCode.USAGE
    mapping = response.as_mapping()
    assert mapping["schema"] == "ledgerwerk.cli.v1"
    assert mapping["ok"] is False
    assert mapping["error"]["code"] == "journal-invalid"  # type: ignore[index]
    assert "journal-invalid" in response.human


def test_recover_cli_invalid_policy_is_non_mutating(tmp_path: Path) -> None:
    journal = tmp_path / "journal.toml"
    journal.write_text("schema_version = 99\n", encoding="utf-8")
    before = journal.read_bytes()

    response = recover_migration(journal, policy="auto", dry_run=True)

    assert response.ok is False
    assert response.exit_code == ExitCode.USAGE
    assert journal.read_bytes() == before


def test_inspect_cli_exposes_schema3_recommendation_and_blockers(
    tmp_path: Path,
) -> None:
    journal = tmp_path / "complete.toml"
    journal.write_text(
        "schema_version = 3\n"
        'migration_id = "cli-test-0001"\n'
        'project_uuid = "project"\n'
        'phase = "complete"\n'
        'mode = "copy"\n'
        'verify = "sha256"\n'
        f'project_root = "{tmp_path}"\n'
        "plan_digest = " + '"' + "0" * 64 + '"\n'
        "requires_staged_validation = false\n"
        "requires_activated_validation = false\n"
        "requires_finalization = false\n"
        "items = {}\n",
        encoding="utf-8",
    )

    response = inspect_migration(journal)

    assert response.ok is True
    result = response.as_mapping()["result"]
    assert result["recommended_action"] == "complete"  # type: ignore[index]
    assert result["blockers"] == []  # type: ignore[index]
