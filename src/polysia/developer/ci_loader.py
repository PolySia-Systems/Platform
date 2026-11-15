"""Load the repository-owned CI selector without duplicating policy."""

import importlib.util
import sys
from collections.abc import Callable
from pathlib import Path

from polysia.developer.git_state import DeveloperContextError

ClassifyPaths = Callable[[tuple[str, ...] | list[str]], object]


def load_classify_paths(root: Path) -> ClassifyPaths:
    path = root / "scripts" / "classify_ci_changes.py"
    if not path.is_file():
        raise DeveloperContextError("CI change classifier is missing")
    spec = importlib.util.spec_from_file_location(
        "polysia_developer_classify_ci_changes",
        path,
    )
    if spec is None or spec.loader is None:
        raise DeveloperContextError("CI change classifier could not be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    classifier = getattr(module, "classify_paths", None)
    if not callable(classifier):
        raise DeveloperContextError("CI change classifier is invalid")
    return classifier
