import shutil
import subprocess
from pathlib import Path
import pytest

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_web_build():
    """Verify web dashboard build succeeds cleanly."""
    npm = shutil.which("npm") or shutil.which("npm.cmd")
    assert npm is not None, "npm not found on system PATH"

    lockfile = WEB_DIR / "package-lock.json"
    install_cmd = [npm, "ci"] if lockfile.exists() else [npm, "install"]
    res_install = subprocess.run(
        install_cmd,
        cwd=WEB_DIR,
        capture_output=True,
        text=True,
        shell=(npm.endswith(".cmd")),
    )
    assert res_install.returncode == 0, f"npm install failed:\n{res_install.stderr}"

    build_cmd = [npm, "run", "build"]
    res_build = subprocess.run(
        build_cmd,
        cwd=WEB_DIR,
        capture_output=True,
        text=True,
        shell=(npm.endswith(".cmd")),
    )
    assert res_build.returncode == 0, f"npm run build failed:\n{res_build.stderr}"
    assert (WEB_DIR / "dist" / "index.html").exists(), "dist/index.html was not generated"
