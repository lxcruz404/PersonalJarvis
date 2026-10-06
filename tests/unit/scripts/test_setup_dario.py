"""scripts/dario/setup_dario.py: dry run changes nothing; apply is backed up and idempotent."""

from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.brain.assistant_name import resolve_assistant_name
from jarvis.core.config import load_config
from jarvis.memory.soul import Soul
from scripts.dario import setup_dario


@pytest.fixture
def install(tmp_path: Path) -> tuple[Path, Path]:
    config = tmp_path / "jarvis.toml"
    config.write_text(
        '# my settings\n[tts]\nprovider = "piper-local"\n\n'
        '[trigger.wake_word]\nphrase = "Hey Nova"\n',
        encoding="utf-8",
    )
    data = tmp_path / "data"
    return config, data


def test_dry_run_changes_nothing(
    install: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    config, data = install
    before = config.read_text(encoding="utf-8")
    assert setup_dario.main(["--config", str(config), "--data-dir", str(data)]) == 0
    assert config.read_text(encoding="utf-8") == before
    assert not (data / "workspace" / "SOUL.md").exists()
    assert "set [profile] name = 'dario'" in capsys.readouterr().out


def test_apply_makes_the_install_dario(install: tuple[Path, Path]) -> None:
    config, data = install
    assert setup_dario.main(["--apply", "--config", str(config), "--data-dir", str(data)]) == 0

    text = config.read_text(encoding="utf-8")
    assert "# my settings" in text and 'provider = "piper-local"' in text  # nothing else lost
    assert list(config.parent.glob("jarvis.toml.bak-dario-*"))

    cfg = load_config(config)
    assert cfg.profile.name == "dario"
    assert resolve_assistant_name(cfg) == "Darío"
    assert cfg.trigger.wake_word.language == "es"
    assert cfg.brain.reply_language == "es"
    assert cfg.ui.language == "es"
    assert cfg.tts.provider == "piper-local"  # provider choice untouched

    soul = Soul.load(data / "workspace" / "SOUL.md")
    assert soul.name == "Darío"
    assert "Colombian" in soul.body


def test_apply_keeps_learned_calibration_and_backs_up_the_old_soul(
    install: tuple[Path, Path],
) -> None:
    config, data = install
    soul_path = data / "workspace" / "SOUL.md"
    soul_path.parent.mkdir(parents=True)
    old = Soul.parse(
        soul_path,
        "---\nschema_version: 1\n---\n\n# Persona\n\n## Who I am\n\n- **Name:** Nova\n\n"
        "## Calibration (learns over time)\n\n<!-- curator:calibration:start -->\n"
        "- The user prefers short answers\n<!-- curator:calibration:end -->\n",
    )
    old.save()

    setup_dario.main(["--apply", "--config", str(config), "--data-dir", str(data)])

    soul = Soul.load(soul_path)
    assert soul.name == "Darío"
    assert [entry.text for entry in soul.learned()] == ["The user prefers short answers"]
    backups = list(soul_path.parent.glob("SOUL.md.bak-dario-*"))
    assert len(backups) == 1 and "Nova" in backups[0].read_text(encoding="utf-8")


def test_apply_twice_is_stable(install: tuple[Path, Path]) -> None:
    config, data = install
    setup_dario.main(["--apply", "--config", str(config), "--data-dir", str(data)])
    first = config.read_text(encoding="utf-8")
    setup_dario.main(["--apply", "--config", str(config), "--data-dir", str(data)])
    assert config.read_text(encoding="utf-8") == first
    assert len(list(config.parent.glob("jarvis.toml.bak-dario-*"))) == 1


def test_profile_overlay_is_identity_and_language_only() -> None:
    import yaml

    overlay = yaml.safe_load(
        setup_dario.REPO_ROOT.joinpath("profiles", "dario.yaml").read_text("utf-8")
    )
    assert set(overlay) == {"profile", "trigger", "stt", "brain", "ui", "tts"}
    assert set(overlay["brain"]) == {"reply_language"}
    assert set(overlay["tts"]) == {"language_code"}
    assert set(overlay["stt"]) == {"bias_prompt"}
