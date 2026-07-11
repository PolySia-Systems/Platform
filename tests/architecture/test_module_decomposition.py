import ast
from pathlib import Path

ROOT = Path(__file__).parents[2]


def _defined_functions(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }


def test_cli_support_is_independent_of_typer_command_wiring() -> None:
    support_root = ROOT / "src" / "polysia" / "cli_support"

    for path in support_root.glob("*.py"):
        assert "import typer" not in path.read_text(encoding="utf-8")


def test_acceptance_service_reexports_but_does_not_define_renderers() -> None:
    service = ROOT / "src" / "polysia" / "monitoring" / "acceptance_audit.py"

    assert not {
        "render_acceptance_audit",
        "render_acceptance_audit_html",
        "render_acceptance_audit_json",
        "render_acceptance_audit_markdown",
    } & _defined_functions(service)


def test_manual_intervention_service_does_not_define_renderers() -> None:
    service = (
        ROOT
        / "src"
        / "polysia"
        / "execution"
        / "manual_intervention_live_test.py"
    )

    assert not {
        "render_manual_intervention_live_test",
        "render_manual_intervention_live_test_markdown",
    } & _defined_functions(service)
