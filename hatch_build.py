"""Build fails on missing/stale UI. It never installs or invokes Node."""

from pathlib import Path
from runpy import run_path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version: str, build_data: dict) -> None:
        root = Path(self.root)
        verifier = run_path(str(root / "src/polysia/monitoring/console_bundle.py"))
        verifier["verify_bundle"](
            root / "src/polysia/monitoring/human_console_assets", source_root=root
        )
