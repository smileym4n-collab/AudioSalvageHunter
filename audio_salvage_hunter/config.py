from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - exercised only on very small Python installs.
    yaml = None


@dataclass(frozen=True)
class AppConfig:
    raw: dict[str, Any]
    path: Path

    @property
    def settings(self) -> dict[str, Any]:
        return self.raw.get("settings", {})

    @property
    def search_groups(self) -> dict[str, list[str]]:
        groups = self.raw.get("search_groups", {})
        return {str(name): [str(term) for term in terms] for name, terms in groups.items()}

    @property
    def scoring_terms(self) -> dict[str, list[str]]:
        terms = self.raw.get("scoring_terms", {})
        return {str(name): [str(term) for term in values] for name, values in terms.items()}

    def setting(self, key: str, default: Any) -> Any:
        return self.settings.get(key, default)


class ConfigError(ValueError):
    pass


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path)
    try:
        with config_path.open("r", encoding="utf-8") as handle:
            if yaml is not None:
                raw = yaml.safe_load(handle) or {}
            else:
                raw = parse_simple_yaml(handle.read())
    except OSError as exc:
        raise ConfigError(f"Could not read configuration file {config_path}: {exc}") from exc
    except Exception as exc:
        raise ConfigError(f"Could not parse configuration file {config_path}: {exc}") from exc
    validate_config(raw)
    return AppConfig(raw=raw, path=config_path)


def validate_config(raw: Any) -> None:
    if not isinstance(raw, dict):
        raise ConfigError("Configuration root must be a mapping.")
    for section in ("settings", "search_groups", "scoring_terms"):
        if section in raw and not isinstance(raw[section], dict):
            raise ConfigError(f"Configuration section '{section}' must be a mapping.")
    for section in ("search_groups", "scoring_terms"):
        values = raw.get(section, {})
        if not isinstance(values, dict):
            continue
        for key, items in values.items():
            if not isinstance(items, list) or not all(isinstance(item, str) for item in items):
                raise ConfigError(f"Configuration value '{section}.{key}' must be a list of strings.")


def parse_scalar(value: str) -> Any:
    value = value.strip()
    if value == "":
        return ""
    lowered = value.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value.strip('"').strip("'")


def parse_simple_yaml(text: str) -> dict[str, Any]:
    """Tiny fallback parser for this project's simple config.yaml shape."""
    root: dict[str, Any] = {}
    current_section: dict[str, Any] | None = None
    current_list: list[str] | None = None
    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        line = raw_line.strip()
        if indent == 0 and line.endswith(":"):
            section_name = line[:-1]
            current_section = {}
            root[section_name] = current_section
            current_list = None
            continue
        if indent == 0 and ":" in line:
            key, value = line.split(":", 1)
            root[key.strip()] = parse_scalar(value)
            current_section = None
            current_list = None
            continue
        if current_section is None:
            continue
        if indent == 2 and line.endswith(":"):
            key = line[:-1]
            current_list = []
            current_section[key] = current_list
            continue
        if indent == 2 and ":" in line:
            key, value = line.split(":", 1)
            current_section[key.strip()] = parse_scalar(value)
            current_list = None
            continue
        if indent >= 4 and line.startswith("- ") and current_list is not None:
            current_list.append(str(parse_scalar(line[2:])))
    return root
