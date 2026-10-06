"""Turn this Personal Jarvis install into Darío.

Two changes, both reversible and both backed up first:

1. ``[profile] name = "dario"`` in jarvis.toml, which makes ``load_config``
   merge ``profiles/dario.yaml`` (wake word "Darío", Spanish wake model,
   Spanish replies and interface). Written through ``jarvis.core.config_writer``
   (lock + atomic replace + BOM-safe), never by hand (AP-7).
2. ``<data>/workspace/SOUL.md`` gets Darío's character from
   ``profiles/dario.SOUL.md``. Notes the assistant already learned about its own
   character (the Calibration section) are carried over.

Nothing else changes: no provider, key, voice or device setting.

Usage (from the repository root):

    python scripts/dario/setup_dario.py            # dry run: show what would change
    python scripts/dario/setup_dario.py --apply    # make the change

Restart the app afterwards; the wake word and voice pipeline read their
settings at start-up. To undo: remove the ``[profile]`` line (or set it back to
"default") and restore the ``SOUL.md.bak-dario-*`` copy.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

PROFILE_NAME = "dario"
SOUL_TEMPLATE = REPO_ROOT / "profiles" / "dario.SOUL.md"


@dataclass(frozen=True)
class Plan:
    config_path: Path
    soul_path: Path
    current_profile: str
    soul_exists: bool

    def describe(self) -> list[str]:
        lines = []
        if self.current_profile == PROFILE_NAME:
            lines.append(f"{self.config_path}: [profile] name is already '{PROFILE_NAME}'")
        else:
            lines.append(
                f"{self.config_path}: set [profile] name = '{PROFILE_NAME}' "
                f"(now '{self.current_profile or 'default'}')"
            )
        if self.soul_exists:
            lines.append(f"{self.soul_path}: replace the character, keep learned calibration notes")
        else:
            lines.append(f"{self.soul_path}: create with Darío's character")
        return lines


def _current_profile(config_path: Path) -> str:
    if not config_path.exists():
        return ""
    import tomllib

    raw = config_path.read_text(encoding="utf-8-sig")
    try:
        data = tomllib.loads(raw)
    except tomllib.TOMLDecodeError as exc:
        raise SystemExit(
            f"{config_path} is not valid TOML; fix it before running this: {exc}"
        ) from exc
    return str(data.get("profile", {}).get("name", "") or "")


def make_plan(config_path: Path, data_dir: Path) -> Plan:
    soul_path = data_dir / "workspace" / "SOUL.md"
    return Plan(
        config_path=config_path,
        soul_path=soul_path,
        current_profile=_current_profile(config_path),
        soul_exists=soul_path.exists(),
    )


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _backup(path: Path, stamp: str) -> Path | None:
    if not path.exists():
        return None
    backup = path.with_name(f"{path.name}.bak-dario-{stamp}")
    shutil.copy2(path, backup)
    return backup


def _install_soul(soul_path: Path) -> None:
    from jarvis.memory.frontmatter import parse_frontmatter
    from jarvis.memory.soul import Soul, edit_soul

    _meta, body = parse_frontmatter(SOUL_TEMPLATE.read_text(encoding="utf-8"))
    if not soul_path.exists():
        soul_path.parent.mkdir(parents=True, exist_ok=True)
        Soul.parse(soul_path, SOUL_TEMPLATE.read_text(encoding="utf-8")).save()
        return

    def replace_character(soul: Soul) -> bool:
        learned = soul.learned()
        changed = soul.set_body(body)
        if learned:
            soul.set_learned(learned)
            changed = True
        return changed

    edit_soul(soul_path, replace_character)


def apply(plan: Plan) -> list[str]:
    """Back up, then write both changes. Returns what was done."""
    from jarvis.core import config_writer

    stamp = _stamp()
    done: list[str] = []
    if plan.current_profile != PROFILE_NAME:
        backup = _backup(plan.config_path, stamp)
        if backup is not None:
            done.append(f"backed up {plan.config_path} to {backup}")
        config_writer._patch_table(plan.config_path, "profile", "name", PROFILE_NAME)
        done.append(f"set [profile] name = '{PROFILE_NAME}' in {plan.config_path}")
    backup = _backup(plan.soul_path, stamp)
    if backup is not None:
        done.append(f"backed up {plan.soul_path} to {backup}")
    _install_soul(plan.soul_path)
    done.append(f"wrote Darío's character to {plan.soul_path}")
    return done


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--apply", action="store_true", help="make the change (default: dry run)")
    parser.add_argument("--config", type=Path, default=None, help="jarvis.toml to change")
    parser.add_argument("--data-dir", type=Path, default=None, help="runtime data directory")
    args = parser.parse_args(argv)

    from jarvis.core import config as core_config

    config_path = args.config or core_config.resolve_config_path()
    data_dir = args.data_dir or core_config.DATA_DIR
    plan = make_plan(config_path, data_dir)

    if not args.apply:
        print("Dry run. With --apply this would:")
        for line in plan.describe():
            print(f"  - {line}")
        return 0
    for line in apply(plan):
        print(f"  - {line}")
    print("Done. Restart Personal Jarvis so the wake word and voice settings take effect.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
