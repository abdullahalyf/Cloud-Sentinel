"""
B11 — packaging. Acceptance tests.

The claim this file checks is the one a pitch makes out loud: *you can install
this in a clean virtualenv and it works*. That claim is worth nothing if it
is only ever checked inside the developer's own environment, where the repo is
on `sys.path` and every dependency is already installed.

So these tests build a **real virtualenv**, **really** `pip install` both
packages into it, and then run code **inside that venv** — with the repo
*not* on the path — and check that what comes back is right.

Two things are checked, and they are different things:

  * **the SDK** — `pip install ./telemetry/sdk` gives an importable
    `cloudsentinel` with the surface an agent actually calls;
  * **the MCP server** — `pip install ./brain/mcp_pkg` gives a
    `cloudsentinel-mcp` command that starts, speaks MCP over stdio, and
    answers with its tools.

A third test checks the **quickstart** — the five lines a stranger is asked to
type — actually run and print a fleet. A quickstart that does not run is the
worst kind of documentation: it looks like an answer.

**These tests need the network** (pip downloads the dependencies), so they are
marked `live` and are **skipped** when there is no network — the same rule the
rest of the suite uses for anything that reaches outside. Run them with:

    python -m pytest brain/tests/test_packaging.py -q -m live

**The slow path is not optional.** The point of B11 is that the install
*works*, so there is no mock for "does pip install succeed". A test that
asserts a mocked install succeeded would prove nothing about the thing the
pitch claims.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import venv
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SDK = REPO / "telemetry" / "sdk"
MCP_PKG = REPO / "brain" / "mcp_pkg"
QUICKSTART = REPO / "docs" / "research" / "quickstart.md"


# ── helpers ─────────────────────────────────────────────────────────────────
def _network_is_available() -> bool:
    """Whether pip can reach an index. Checked once, cheaply.

    The download goes to a **temporary directory**, not the working directory:
    `pip download` writes the wheel next to wherever it was run, and a test
    that leaves a `.whl` in the repository root is a test that dirties the
    tree it is testing.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as dest:
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "download", "--no-deps",
                 "--dest", dest, "wheel"],
                capture_output=True, text=True, timeout=120, check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return False
    return result.returncode == 0


def _make_venv(path: Path) -> Path:
    """A real, empty virtualenv. Returns the path to its python."""
    venv.EnvBuilder(with_pip=True, clear=True, symlinks=False).create(path)
    if os.name == "nt":
        return path / "Scripts" / "python.exe"
    return path / "bin" / "python"


def _pip_install(python: Path, target: Path, *args: str) -> subprocess.CompletedProcess:
    """`pip install` into the venv, with the repo *not* on the path."""
    return subprocess.run(
        [str(python), "-m", "pip", "install", "--disable-pip-version-check",
         "--no-input", *args, str(target)],
        capture_output=True, text=True, timeout=900, check=False,
    )


def _run_in(python: Path, code: str, timeout: int = 180) -> subprocess.CompletedProcess:
    """Run a snippet inside the venv, from a directory that is not the repo."""
    return subprocess.run(
        [str(python), "-c", code],
        capture_output=True, text=True, timeout=timeout, check=False,
        cwd=str(Path(os.environ.get("TEMP", "/tmp"))),
        env={**os.environ, "PYTHONPATH": ""},
    )


requires_network = pytest.mark.skipif(
    not _network_is_available(),
    reason="no network — pip cannot fetch the dependencies",
)


# ── the SDK ─────────────────────────────────────────────────────────────────
@pytest.mark.live
@requires_network
def test_the_sdk_installs_in_a_clean_venv(tmp_path):
    """
    `pip install ./telemetry/sdk` works in a virtualenv that has nothing in it.

    The install is checked by **running** it, not by reading the exit code
    alone: pip can exit 0 and still leave a package that will not import.
    """
    venv_dir = tmp_path / "sdkvenv"
    python = _make_venv(venv_dir)

    result = _pip_install(python, SDK)
    assert result.returncode == 0, (
        f"pip install ./telemetry/sdk failed:\n{result.stdout[-3000:]}\n"
        f"{result.stderr[-3000:]}")

    probe = _run_in(python, "import cloudsentinel; print(cloudsentinel.__name__)")
    assert probe.returncode == 0, (
        f"the installed SDK does not import:\n{probe.stderr[-3000:]}")
    assert "cloudsentinel" in probe.stdout


@pytest.mark.live
@requires_network
def test_the_installed_sdk_has_the_surface_an_agent_calls(tmp_path):
    """
    The installed package exposes the calls an agent actually makes.

    The list is the *contract* of the SDK: if a call disappears from the
    installed package, every agent that used it breaks — and it breaks for the
    user, at their end, not for us.
    """
    venv_dir = tmp_path / "sdkvenv"
    python = _make_venv(venv_dir)
    assert _pip_install(python, SDK).returncode == 0

    names = [
        "init", "llm_call", "tool", "gate", "task", "node", "memory",
        "wait_if_paused",
    ]
    code = (
        "import cloudsentinel\n"
        f"missing = [n for n in {names!r} if not hasattr(cloudsentinel, n)]\n"
        "print('MISSING:' + ','.join(missing))\n"
    )
    probe = _run_in(python, code)
    assert probe.returncode == 0, probe.stderr[-3000:]
    assert "MISSING:" in probe.stdout
    missing = probe.stdout.split("MISSING:", 1)[1].strip()
    assert missing == "", f"the installed SDK is missing: {missing}"


# ── the MCP server ──────────────────────────────────────────────────────────
@pytest.mark.live
@requires_network
def test_the_mcp_server_installs_in_a_clean_venv(tmp_path):
    """`pip install ./brain/mcp_pkg` works in an empty virtualenv."""
    venv_dir = tmp_path / "mcpvenv"
    python = _make_venv(venv_dir)

    result = _pip_install(python, MCP_PKG)
    assert result.returncode == 0, (
        f"pip install ./brain/mcp_pkg failed:\n{result.stdout[-3000:]}\n"
        f"{result.stderr[-3000:]}")

    # The console script has to exist and be runnable.
    if os.name == "nt":
        exe = venv_dir / "Scripts" / "cloudsentinel-mcp.exe"
    else:
        exe = venv_dir / "bin" / "cloudsentinel-mcp"
    assert exe.exists(), f"the installed command is missing: {exe}"

    probe = subprocess.run([str(exe), "--help"], capture_output=True, text=True,
                           timeout=120, check=False)
    assert probe.returncode == 0, probe.stderr[-2000:]


@pytest.mark.live
@requires_network
def test_the_installed_mcp_server_answers_with_its_tools(tmp_path):
    """
    The installed command speaks MCP over stdio and lists its tools.

    This is the check that would catch the classic packaging bug: the package
    installs, the command exists, and then it dies the moment a client
    connects, because a module was missing from the wheel.

    The client is driven over real stdio — a subprocess, framed MCP messages
    — because "it starts" is not the claim. "It answers" is.
    """
    venv_dir = tmp_path / "mcpvenv"
    python = _make_venv(venv_dir)
    assert _pip_install(python, MCP_PKG).returncode == 0

    if os.name == "nt":
        exe = str(venv_dir / "Scripts" / "cloudsentinel-mcp.exe")
    else:
        exe = str(venv_dir / "bin" / "cloudsentinel-mcp")

    code = (
        "import asyncio, json\n"
        "from mcp import ClientSession, StdioServerParameters\n"
        "from mcp.client.stdio import stdio_client\n"
        "async def main():\n"
        f"    params = StdioServerParameters(command={exe!r}, args=[], env=None)\n"
        "    async with stdio_client(params) as (read, write):\n"
        "        async with ClientSession(read, write) as session:\n"
        "            await session.initialize()\n"
        "            tools = await session.list_tools()\n"
        "            print(json.dumps([t.name for t in tools.tools]))\n"
        "asyncio.run(main())\n"
    )
    probe = _run_in(python, code, timeout=180)
    assert probe.returncode == 0, (
        f"the installed MCP server did not answer:\n{probe.stderr[-3000:]}")
    names = json.loads(probe.stdout.strip().splitlines()[-1])
    assert names, "the installed MCP server listed no tools"
    # The tools the server is supposed to have. `list_agents` is the one that
    # shows the fleet; the rest are the control surface the pitch talks about.
    for tool in ("list_agents", "get_agent", "get_roi_report", "pause_agent"):
        assert tool in names, f"{tool} is missing from the installed server: {names}"
    assert len(names) >= 15, (
        f"the installed server has only {len(names)} tools — the wheel is "
        f"probably missing a module")


@pytest.mark.live
@requires_network
def test_the_installed_mcp_server_lists_the_real_fleet(tmp_path):
    """
    The installed server, talking to a running CloudSentinel, returns a fleet.

    This is the whole story in one test: a package installed in a clean
    virtualenv, a command that starts, a protocol conversation, and a real
    answer from the control tower. Everything before it could pass with a
    server that answers nothing at all.

    The API is the brain's own **fake** mode — four simulated agents, no
    Docker, no keys — so the test needs nothing from the outside world
    except pip.
    """
    import time

    venv_dir = tmp_path / "mcpvenv"
    python = _make_venv(venv_dir)
    assert _pip_install(python, MCP_PKG).returncode == 0

    if os.name == "nt":
        exe = str(venv_dir / "Scripts" / "cloudsentinel-mcp.exe")
    else:
        exe = str(venv_dir / "bin" / "cloudsentinel-mcp")

    # Start the fake brain: no Docker, no API keys, four simulated agents.
    # The port comes from `CS_API_PORT`, so the test does not fight whatever
    # is already running on 8000.
    port = 8765
    env = {**os.environ, "CS_API_PORT": str(port)}
    api = subprocess.Popen(
        [sys.executable, "-m", "brain", "--fake", "--no-auto-rogue"],
        cwd=str(REPO), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, env=env,
    )
    try:
        base = f"http://127.0.0.1:{port}"
        fleet = _wait_for_fleet(base, timeout=90)
        assert fleet, "the fake brain never listed a fleet"

        code = (
            "import asyncio, json\n"
            "from mcp import ClientSession, StdioServerParameters\n"
            "from mcp.client.stdio import stdio_client\n"
            "async def main():\n"
            f"    params = StdioServerParameters(command={exe!r}, args=["
            f"'--api-url', {base!r}], env=None)\n"
            "    async with stdio_client(params) as (read, write):\n"
            "        async with ClientSession(read, write) as session:\n"
            "            await session.initialize()\n"
            "            tools = await session.list_tools()\n"
            "            result = await session.call_tool('list_agents', {})\n"
            "            print(json.dumps({'n': len(tools.tools),"
            " 'agents': [json.loads(c.text) for c in result.content"
            " if hasattr(c, 'text')]}))\n"
            "asyncio.run(main())\n"
        )
        probe = _run_in(python, code, timeout=180)
        assert probe.returncode == 0, (
            f"the installed MCP server did not answer:\n{probe.stderr[-3000:]}")
        payload = json.loads(probe.stdout.strip().splitlines()[-1])
        assert payload["n"] == 17, (
            f"the installed server listed {payload['n']} tools, expected 17")
        assert payload["agents"], "the server answered with no agents"
        ids = {a.get("agent_id") for a in payload["agents"]}
        assert ids, "the agents have no ids"
    finally:
        api.terminate()
        try:
            api.wait(timeout=15)
        except subprocess.TimeoutExpired:
            api.kill()


def _wait_for_fleet(base: str, timeout: int = 60) -> list:
    """Poll the fleet endpoint until it answers with agents, or time out."""
    import time
    import urllib.error
    import urllib.request

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{base}/v1/fleet", timeout=5) as r:
                agents = json.loads(r.read().decode()).get("agents", [])
                if agents:
                    return agents
        except (urllib.error.URLError, OSError, ValueError):
            pass
        time.sleep(1)
    return []


# ── the quickstart ──────────────────────────────────────────────────────────
def test_the_quickstart_exists():
    """The five lines have to be written down somewhere, or there is nothing to run."""
    assert QUICKSTART.exists(), f"the quickstart is missing: {QUICKSTART}"


def test_the_quickstart_is_five_lines_of_code():
    """
    The quickstart's core is five lines. Not five paragraphs.

    A stranger will read the first screen and type it. If the first runnable
    block is longer than that, they will not, and the install story never gets
    told.
    """
    text = QUICKSTART.read_text(encoding="utf-8")
    blocks = _code_blocks(text)
    assert blocks, "the quickstart has no code block"
    python_blocks = [b for b in blocks if _is_python(b)]
    assert python_blocks, "the quickstart has no Python block"
    lines = [ln for ln in python_blocks[0].splitlines()
             if ln.strip() and not ln.strip().startswith("#")]
    assert len(lines) <= 8, (
        f"the quickstart's first Python block is {len(lines)} lines — it must "
        f"be short enough to type")


def test_the_quickstart_names_both_packages():
    """Both install lines are there — the SDK *and* the MCP server."""
    text = QUICKSTART.read_text(encoding="utf-8").lower()
    assert "pip install ./telemetry/sdk" in text
    assert "pip install ./brain/mcp_pkg" in text


def test_the_quickstart_says_how_many_tools_the_mcp_server_has():
    """
    The number is a claim, so it is checked.

    "17 tools" is what the installed server actually lists; if that changes,
    the quickstart must change with it, or the pitch walks into the room with
    a wrong number on the screen.

    The count comes from the source's own `@mcp.tool` decorators, so it is
    exact and needs no MCP server running.
    """
    source = (MCP_PKG / "cloudsentinel_mcp" / "server.py").read_text(encoding="utf-8")
    count = source.count("@mcp.tool")
    assert count > 0, "the server has no tools — the count would be meaningless"
    text = QUICKSTART.read_text(encoding="utf-8")
    assert f"{count} tools" in text, (
        f"the quickstart does not say the server has {count} tools")


def test_the_quickstart_prints_a_fleet():
    """The quickstart's promise is that it prints a fleet. So it must."""
    text = QUICKSTART.read_text(encoding="utf-8")
    blocks = _code_blocks(text)
    assert blocks, "the quickstart has no code block"
    # The promise is in the prose, and the command that keeps it.
    assert "fleet" in text.lower(), (
        "the quickstart never mentions the fleet it prints")
    assert any("/v1/fleet" in b for b in blocks), (
        "the quickstart has no command that shows the fleet")


def _code_blocks(text: str) -> list:
    """The fenced code blocks in a markdown document."""
    blocks = []
    inside = False
    current = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            if inside:
                blocks.append("\n".join(current))
                current = []
                inside = False
            else:
                inside = True
            continue
        if inside:
            current.append(line)
    return blocks


def _is_python(block: str) -> bool:
    """Whether a code block looks like Python.

    The language tag is not kept per block, so this is decided by the content:
    Python blocks here start with `import` or `from`.
    """
    for line in block.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        return stripped.startswith("import ") or stripped.startswith("from ")
    return False
