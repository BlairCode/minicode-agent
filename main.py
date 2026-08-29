from __future__ import annotations

import argparse
import sys
from pathlib import Path

from minicode_agent.app import Application
from minicode_agent.cli import run_console
from minicode_agent.config import ConfigError, load_config
from minicode_agent.personal import (
    CredentialStore,
    PersonalSettings,
    PersonalSettingsStore,
    user_data_directory,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the MiniCode local coding agent")
    parser.add_argument("--config", help="Optional user YAML merged over config/default.yaml")
    parser.add_argument("--workspace", help="Override the configured workspace")
    parser.add_argument("--agent", choices=("coding", "leetcode"), help="Initial agent")
    parser.add_argument("--cli", action="store_true", help="Use the terminal interface instead of the local web UI")
    parser.add_argument("--no-browser", action="store_true", help="Start the local web UI without opening a browser")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    project_root = Path(__file__).resolve().parent
    try:
        config = load_config(project_root / "config" / "default.yaml", args.config)
        data_dir = user_data_directory(config.storage.data_dir)
        settings_store = PersonalSettingsStore(data_dir)
        settings = settings_store.load(PersonalSettings.from_config(config))
        settings.apply(config)
        if args.workspace:
            config.workspace.root = args.workspace
            settings.workspace = args.workspace
        if args.agent:
            config.agent.default = args.agent
        config.validate()
        try:
            credential_store = CredentialStore()
        except RuntimeError:
            credential_store = None

        def credential() -> str | None:
            return credential_store.get(config.model.provider) if credential_store else None

        app = Application(config, project_root=project_root, credential_provider=credential)
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    if args.cli:
        return run_console(app)
    try:
        from minicode_agent.web import run_web

        return run_web(
            app,
            config,
            project_root,
            settings,
            settings_store,
            credential_store,
            open_browser=config.ui.open_browser and not args.no_browser,
        )
    except Exception as exc:
        print(f"Cannot start local web UI: {type(exc).__name__}: {exc}", file=sys.stderr)
        print("Use --cli in a headless environment.", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
