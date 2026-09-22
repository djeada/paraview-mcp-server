#!/usr/bin/env python3
"""Drive the ParaView MCP server through real scenarios and report what happened.

This is an end-to-end harness, not a unit test. It starts a real ParaView
bridge, connects to the real MCP server as a real MCP client over stdio, and
runs each scenario's tool calls against a live ParaView session:

    run_scenarios.py (MCP client) → paraview-mcp-server → bridge → ParaView

Usage:
    python demos/run_scenarios.py                 # run everything, write a report
    python demos/run_scenarios.py --only 04 05    # run selected scenarios
    python demos/run_scenarios.py --keep-going    # do not stop at the first failure

Every process this starts is tracked and torn down on exit, including on
Ctrl-C. Rendering happens inside an Xvfb display when one is available, so no
windows appear on your desktop.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402
from scenarios import Scenario, build_scenarios, dataset_generator_script  # noqa: E402

DEFAULT_BRIDGE_PORT = 9899  # deliberately not 9876, to avoid a bridge you already run


# ---------------------------------------------------------------------------
# Process supervision
# ---------------------------------------------------------------------------


@dataclass
class Supervisor:
    """Tracks every child process so none can outlive the run.

    Children are started in their own process group and torn down by group.
    Signalling only the direct child is not enough: `xvfb-run` is a shell
    wrapper, so killing it orphans the Xvfb and pvpython processes it started,
    and those keep a ParaView session and an X server alive indefinitely.
    """

    procs: list[tuple[str, subprocess.Popen]] = field(default_factory=list)

    def spawn(self, name: str, command: list[str], **kwargs) -> subprocess.Popen:
        kwargs.setdefault("start_new_session", True)
        proc = subprocess.Popen(command, **kwargs)
        self.procs.append((name, proc))
        return proc

    @staticmethod
    def _signal_group(proc: subprocess.Popen, sig: int) -> None:
        try:
            os.killpg(os.getpgid(proc.pid), sig)
        except (ProcessLookupError, PermissionError, OSError):
            with contextlib.suppress(OSError):
                proc.send_signal(sig)

    def shutdown(self) -> None:
        for name, proc in reversed(self.procs):
            if proc.poll() is not None:
                continue
            self._signal_group(proc, signal.SIGTERM)
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self._signal_group(proc, signal.SIGKILL)
                with contextlib.suppress(subprocess.TimeoutExpired):
                    proc.wait(timeout=5)
            print(f"  stopped {name} (pid {proc.pid})")
        self.procs.clear()
        self.report_survivors()

    @staticmethod
    def report_survivors(settle_seconds: float = 6.0) -> None:
        """Warn if anything we started is still around once it has had time to exit.

        A signalled ParaView process takes a moment to unwind, so poll for a
        few seconds before complaining: reporting immediately turns every
        normal shutdown into a false alarm.
        """
        deadline = time.monotonic() + settle_seconds
        survivors: list[str] = []
        while time.monotonic() < deadline:
            try:
                listing = subprocess.run(  # noqa: S603
                    ["ps", "-eo", "pid,ppid,comm"],
                    capture_output=True,
                    text=True,
                    timeout=15,
                    check=False,
                ).stdout
            except (OSError, subprocess.SubprocessError):
                return
            survivors = [
                line
                for line in listing.splitlines()[1:]
                if any(token in line for token in ("pvpython", "pvserver", "Xvfb"))
            ]
            if not survivors:
                return
            time.sleep(0.5)

        print("  WARNING: ParaView-related processes are still running:")
        for line in survivors:
            print(f"    {line.strip()}")
        print("  If they are not yours, kill them before the next run.")


def port_is_open(host: str, port: int, timeout: float = 0.3) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def wait_for_port(host: str, port: int, timeout: float, proc: subprocess.Popen) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if port_is_open(host, port):
            return True
        if proc.poll() is not None:
            return False
        time.sleep(0.2)
    return False


def resolve_pvpython() -> str:
    binary = os.environ.get("PVPYTHON_BIN") or shutil.which("pvpython")
    if not binary:
        raise SystemExit(
            "pvpython not found. Install ParaView or set PVPYTHON_BIN, e.g.\n"
            "  export PVPYTHON_BIN=/opt/ParaView/bin/pvpython"
        )
    return binary


def xvfb_prefix() -> list[str]:
    """Run ParaView inside a throwaway X display when we can."""
    if os.environ.get("PARAVIEW_MCP_DEMO_NO_XVFB") == "1":
        return []
    if shutil.which("xvfb-run"):
        return ["xvfb-run", "-a"]
    return []


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


@dataclass
class StepResult:
    tool: str
    args: dict[str, Any]
    note: str
    ok: bool
    result: Any
    elapsed: float
    screenshot: str | None = None
    failure: str = ""


@dataclass
class ScenarioResult:
    scenario: Scenario
    steps: list[StepResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(step.ok for step in self.steps)


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------


def parse_tool_payload(raw: Any) -> Any:
    """Tools return a JSON string in a text content block; unwrap it."""
    if raw.isError:
        text = "".join(getattr(block, "text", "") for block in raw.content)
        return {"__error__": text}
    text = "".join(getattr(block, "text", "") for block in raw.content)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"__raw__": text}


async def poll_job(session: ClientSession, timeout: float = 120.0) -> Any:
    listed = parse_tool_payload(await session.call_tool("paraview_job_list", {}))
    jobs = listed.get("jobs", [])
    if not jobs:
        return {"__error__": "no jobs to poll"}
    job_id = jobs[-1]["job_id"]

    deadline = time.monotonic() + timeout
    status: Any = {}
    while time.monotonic() < deadline:
        status = parse_tool_payload(await session.call_tool("paraview_job_status", {"job_id": job_id}))
        if status.get("status") not in {"queued", "running"}:
            return status
        await asyncio.sleep(0.5)
    return status


def substitute(value: Any, context: dict[str, Any]) -> Any:
    """Replace "$name" placeholders with values bound by earlier steps."""
    if isinstance(value, str) and value.startswith("$"):
        key = value[1:]
        if key not in context:
            raise KeyError(f"no earlier step bound ${key}")
        return context[key]
    if isinstance(value, dict):
        return {k: substitute(v, context) for k, v in value.items()}
    if isinstance(value, list):
        return [substitute(v, context) for v in value]
    return value


async def run_scenario(
    session: ClientSession, scenario: Scenario, outdir: Path, context: dict[str, Any]
) -> ScenarioResult:
    outcome = ScenarioResult(scenario)
    print(f"\n── {scenario.ident}: {scenario.title}")
    print(f'   prompt: "{scenario.prompt}"')

    for step in scenario.steps:
        started = time.monotonic()
        try:
            args = substitute(step.args, context)
            if step.tool == "__poll_job__":
                payload = await poll_job(session)
            elif step.tool == "__check_animation_frames__":
                stem = Path(outdir / "12-animation").stem
                frames = sorted(outdir.glob(f"{stem}*.png"))
                payload = {"frames": len(frames), "files": [f.name for f in frames[:5]]}
            else:
                payload = parse_tool_payload(await session.call_tool(step.tool, args))
            for name, field_name in step.bind.items():
                if isinstance(payload, dict) and field_name in payload:
                    context[name] = payload[field_name]
        except Exception as exc:  # noqa: BLE001 - report, do not abort the run
            payload = {"__error__": f"{type(exc).__name__}: {exc}"}
            args = step.args
        elapsed = time.monotonic() - started

        failure = ""
        try:
            ok = bool(step.check(payload)) if step.check else "__error__" not in payload
        except Exception as exc:  # noqa: BLE001 - a check that raises is a failure
            ok = False
            failure = f"check raised {type(exc).__name__}: {exc}"

        if not ok and not failure:
            failure = json.dumps(payload)[:400]

        outcome.steps.append(
            StepResult(
                tool=step.tool,
                args=args if isinstance(args, dict) else step.args,
                note=step.note,
                ok=ok,
                result=payload,
                elapsed=elapsed,
                screenshot=step.screenshot,
                failure=failure,
            )
        )
        mark = "✓" if ok else "✗"
        print(f"   {mark} {step.tool} ({elapsed:.2f}s)")
        if not ok:
            print(f"      → {failure}")

    return outcome


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def write_report(results: list[ScenarioResult], outdir: Path, report_path: Path, meta: dict[str, str]) -> None:
    lines: list[str] = []
    passed = sum(1 for r in results if r.ok)
    total = len(results)

    lines.append("# ParaView MCP — demo scenario run")
    lines.append("")
    lines.append(f"**{passed}/{total} scenarios passed.**")
    lines.append("")
    lines.append("| | |")
    lines.append("|---|---|")
    for key, value in meta.items():
        lines.append(f"| {key} | {value} |")
    lines.append("")
    lines.append(
        "Each scenario below is a prompt a user could give an MCP client, the tool calls that "
        "satisfy it, and what ParaView actually returned. Regenerate with `python demos/run_scenarios.py`."
    )
    lines.append("")

    for outcome in results:
        scenario = outcome.scenario
        mark = "PASS" if outcome.ok else "FAIL"
        lines.append(f"## {scenario.ident} — {scenario.title} ({mark})")
        lines.append("")
        lines.append(f"> **Prompt:** {scenario.prompt}")
        lines.append("")
        lines.append("| Step | Tool | Result |")
        lines.append("|---|---|---|")
        for step in outcome.steps:
            summary = json.dumps(step.result)
            if len(summary) > 160:
                summary = summary[:157] + "…"
            summary = summary.replace("|", "\\|")
            status = "✓" if step.ok else "✗"
            lines.append(f"| {status} | `{step.tool}` | `{summary}` |")
        lines.append("")
        for step in outcome.steps:
            if step.note:
                lines.append(f"- **`{step.tool}`** — {step.note}")
        lines.append("")
        for step in outcome.steps:
            if step.screenshot and (outdir / step.screenshot).is_file():
                lines.append(f"![{scenario.title}](images/{step.screenshot})")
                lines.append("")
        if not outcome.ok:
            lines.append("**Failures**")
            lines.append("")
            for step in outcome.steps:
                if not step.ok:
                    lines.append(f"- `{step.tool}`: {step.failure}")
            lines.append("")

    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport written to {report_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def drive(args, supervisor: Supervisor, outdir: Path, bridge_port: int) -> list[ScenarioResult]:
    dataset = str(outdir / "demo.vti")
    scenarios = build_scenarios(dataset, outdir)
    if args.only:
        wanted = tuple(args.only)
        scenarios = [s for s in scenarios if s.ident.startswith(wanted) or s.ident.split("-")[0] in wanted]
        if not scenarios:
            raise SystemExit(f"No scenarios matched {args.only}")

    env = dict(os.environ)
    env["PARAVIEW_MCP_BRIDGE_HOST"] = "127.0.0.1"
    env["PARAVIEW_MCP_BRIDGE_PORT"] = str(bridge_port)
    env["PYTHONPATH"] = os.pathsep.join([str(REPO_ROOT / "src"), env.get("PYTHONPATH", "")]).rstrip(os.pathsep)

    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", "paraview_mcp_server.server"],
        env=env,
    )

    results: list[ScenarioResult] = []
    async with stdio_client(server) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        tools = await session.list_tools()
        print(f"  MCP server exposes {len(tools.tools)} tools")

        # Shared across scenarios: later ones address objects earlier ones made.
        context: dict[str, Any] = {}
        for scenario in scenarios:
            outcome = await run_scenario(session, scenario, outdir, context)
            results.append(outcome)
            if not outcome.ok and not args.keep_going:
                print("\nStopping after first failing scenario (use --keep-going to continue).")
                break
    return results


def install_signal_handlers() -> None:
    """Turn termination signals into exceptions so teardown still runs.

    Python's default SIGTERM handling exits without unwinding, which would
    leave pvpython and pvserver children orphaned.
    """

    def raise_interrupt(signum, _frame):
        raise KeyboardInterrupt(f"signal {signum}")

    for sig in (signal.SIGTERM, signal.SIGHUP):
        with contextlib.suppress(AttributeError, ValueError, OSError):
            signal.signal(sig, raise_interrupt)


def main() -> int:
    install_signal_handlers()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", nargs="*", default=None, help="Scenario ids or prefixes, e.g. 04 05")
    parser.add_argument("--keep-going", action="store_true", help="Continue past a failing scenario")
    parser.add_argument("--bridge-port", type=int, default=DEFAULT_BRIDGE_PORT)
    parser.add_argument("--outdir", default=str(Path(__file__).resolve().parent / "output"))
    parser.add_argument("--report", default=str(REPO_ROOT / "docs" / "demo-run.md"))
    args = parser.parse_args()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    pvpython = resolve_pvpython()
    prefix = xvfb_prefix()
    supervisor = Supervisor()

    if port_is_open("127.0.0.1", args.bridge_port):
        raise SystemExit(
            f"Port {args.bridge_port} is already in use. Stop whatever is listening there, "
            "or pass --bridge-port with a free port."
        )

    try:
        # 1. Generate the dataset the scenarios load.
        dataset = outdir / "demo.vti"
        print(f"Generating demo dataset at {dataset}")
        gen = outdir / "_generate_dataset.py"
        gen.write_text(dataset_generator_script(str(dataset)), encoding="utf-8")
        completed = subprocess.run(  # noqa: S603
            [*prefix, pvpython, str(gen)],
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        if not dataset.is_file():
            print(completed.stdout[-2000:])
            print(completed.stderr[-2000:], file=sys.stderr)
            raise SystemExit("Could not generate the demo dataset")

        # 2. Start the ParaView bridge.
        #    Render control is opted in explicitly: the scenarios take
        #    screenshots, and this bridge is a standalone pvpython client.
        bridge_env = dict(os.environ)
        bridge_env["PYTHONPATH"] = os.pathsep.join([str(REPO_ROOT / "src"), bridge_env.get("PYTHONPATH", "")]).rstrip(
            os.pathsep
        )
        bridge_env["PARAVIEW_MCP_ALLOW_DETACHED_RENDER_WINDOW"] = "1"

        bridge_log = (outdir / "bridge.log").open("wb")
        print(f"Starting ParaView bridge on 127.0.0.1:{args.bridge_port}")
        bridge = supervisor.spawn(
            "paraview bridge",
            [
                *prefix,
                pvpython,
                str(REPO_ROOT / "scripts" / "start_paraview_bridge.py"),
                "--host",
                "127.0.0.1",
                "--port",
                str(args.bridge_port),
            ],
            env=bridge_env,
            stdout=bridge_log,
            stderr=subprocess.STDOUT,
        )
        if not wait_for_port("127.0.0.1", args.bridge_port, timeout=120, proc=bridge):
            print((outdir / "bridge.log").read_text(errors="replace")[-3000:], file=sys.stderr)
            raise SystemExit("The ParaView bridge did not start listening")
        print(f"  bridge ready (pid {bridge.pid})")

        # 3. Drive the MCP server as a client.
        results = asyncio.run(drive(args, supervisor, outdir, args.bridge_port))

    except KeyboardInterrupt:
        print("\nInterrupted.")
        raise
    finally:
        print("\nTearing down:")
        supervisor.shutdown()
        with contextlib.suppress(Exception):
            bridge_log.close()

    meta = {
        "ParaView": subprocess.run(  # noqa: S603
            [pvpython, "-c", "import paraview; print(paraview.__version__)"],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        ).stdout.strip()
        or "unknown",
        "Bridge": f"standalone pvpython on 127.0.0.1:{args.bridge_port}",
        "Render control": "PARAVIEW_MCP_ALLOW_DETACHED_RENDER_WINDOW=1 (headless screenshots)",
        "Display": "Xvfb" if prefix else os.environ.get("DISPLAY", "none"),
    }
    write_report(results, outdir, Path(args.report), meta)

    passed = sum(1 for r in results if r.ok)
    print(f"{passed}/{len(results)} scenarios passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
