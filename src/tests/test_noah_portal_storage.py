from pathlib import Path
import shutil
import subprocess

import pytest


def test_portal_preserves_filters_and_selections_when_migrating_namespaces():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js required for portal storage regression")
    source = Path(__file__).resolve().parents[1]
    subprocess.run(
        [node, str(source / "tests" / "noah_portal_storage.cjs"), str(source / "job_portal" / "portal.js")],
        check=True, capture_output=True, text=True, timeout=10,
    )
