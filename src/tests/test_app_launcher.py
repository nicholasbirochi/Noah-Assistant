from pathlib import Path
import runpy
import sys
from types import SimpleNamespace


def test_app_bundle_runs_noah_launcher(monkeypatch):
    calls = []
    monkeypatch.setitem(sys.modules, "menubar", SimpleNamespace(main=lambda: calls.append("main")))
    scripts = Path(__file__).resolve().parents[1] / "scripts"

    runpy.run_path(str(scripts / "noah_app_main.py"), run_name="__main__")

    assert calls == ["main"]
