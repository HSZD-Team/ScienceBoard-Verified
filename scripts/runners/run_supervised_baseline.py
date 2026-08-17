"""Unified supervised baseline runner for ScienceBoard VM applications.

The runner has two process roles:

* supervisor mode: schedules selected tasks, starts one worker per task attempt,
  watches task progress, handles timeouts, records run-state.json, and stops the
  target VM after infrastructure failures.
* worker mode: runs exactly one ScienceBoard task through AllInOne + AIOAgent.

This replaces the per-application baseline launchers while preserving the
supervised execution behavior used in recent reproduction runs.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import requests
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

LOCAL_ENV_FILE = REPO_ROOT / "scienceboard.local.env"
LOCAL_ENV_KEYS = frozenset(
    {
        "SCIENCEBOARD_BASE_URL",
        "NIMABO_API_KEY",
        "SOGENPORT_API_KEY",
        "OPENAI_API_KEY",
        "SCIENCEBOARD_VM_PROXY",
    }
)

DEFAULT_VM = Path(r"D:\ScienceBoard-Reproduction\VM-worker-01\Ubuntu.vmx")
DEFAULT_VMWARE_BIN = Path(r"D:\VMware\VMware Workstation")
DEFAULT_BASE_URL = "https://nimabo.io/v1"
DEFAULT_MODEL = "gpt-5.6-sol"
DEFAULT_REASON_EFFORT = "xhigh"
DEFAULT_NO_PROGRESS_TIMEOUT = 8 * 60
DEFAULT_TASK_TIMEOUT = 45 * 60
DEFAULT_INFRASTRUCTURE_RETRIES = 1
DEFAULT_API_TIMEOUT = 120
DEFAULT_API_TIMEOUT_ATTEMPTS = 2
DEFAULT_EXTERNAL_NETWORK_CONNECT_TIMEOUT = 10
DEFAULT_EXTERNAL_NETWORK_TIMEOUT = 30
API_TIMEOUT_EVENT_COUNT = 0
TRANSIENT_API_ERRORS = (
    requests.exceptions.Timeout,
    requests.exceptions.ConnectionError,
    requests.exceptions.ChunkedEncodingError,
)
STATE_REPLACE_ATTEMPTS = 8
STATE_REPLACE_INITIAL_DELAY = 0.05

DEFAULT_TEXSTUDIO_SNAPSHOT = "sci_bench"
DEFAULT_CHIMERAX_READY_TIMEOUT = 30.0
DEFAULT_CHIMERAX_READY_POLL_INTERVAL = 1.0
DEFAULT_HEADLESS_A11Y_REQUEST_TIMEOUT = 60.0
EMPTY_A11Y_TREE_FALLBACK = (
    "tag\tname\ttext\tclass\tdescription\tposition (top-left x&y)\tsize (w&h)"
)

API_KEY_PLACEHOLDERS = {
    "PASTE_YOUR_NIMABO_API_KEY_HERE",
    "PASTE_YOUR_SOGENPORT_API_KEY_HERE",
    "PASTE_YOUR_OPENAI_API_KEY_HERE",
}


def replace_with_retry(source: Path, target: Path) -> None:
    delay = STATE_REPLACE_INITIAL_DELAY
    for attempt in range(1, STATE_REPLACE_ATTEMPTS + 1):
        try:
            source.replace(target)
            return
        except PermissionError:
            if attempt == STATE_REPLACE_ATTEMPTS:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 0.5)


@dataclass(frozen=True)
class AppConfig:
    app: str
    task_dir: str
    log_slug: str
    default_snapshot: str | None = None


APP_CONFIGS: dict[str, AppConfig] = {
    "Celestia": AppConfig("Celestia", "Celestia", "celestia"),
    "ChimeraX": AppConfig("ChimeraX", "ChimeraX", "chimerax"),
    "GrassGIS": AppConfig("GrassGIS", "GrassGIS", "grassgis"),
    "KAlgebra": AppConfig("KAlgebra", "KAlgebra", "kalgebra"),
    "Lean": AppConfig("Lean", "Lean", "lean"),
    "TeXstudio": AppConfig(
        "TeXstudio",
        "TeXstudio",
        "texstudio",
        default_snapshot=DEFAULT_TEXSTUDIO_SNAPSHOT,
    ),
}


def import_scienceboard() -> tuple[Any, Any, Any, Any, Any]:
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from sci import AIOAgent, AllInOne, Automata, OBS, Tester

    return AIOAgent, AllInOne, Automata, OBS, Tester


def load_local_env() -> bool:
    """Load the small local credential file without accepting broad shell syntax."""
    if not LOCAL_ENV_FILE.is_file():
        return False

    for line_number, raw_line in enumerate(
        LOCAL_ENV_FILE.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ").lstrip()

        key, separator, value = line.partition("=")
        key = key.strip()
        if not separator or key not in LOCAL_ENV_KEYS:
            expected = ", ".join(sorted(LOCAL_ENV_KEYS))
            raise SystemExit(
                f"Invalid entry in {LOCAL_ENV_FILE.name}:{line_number}. "
                f"Only {expected} are supported."
            )

        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ[key] = value
    return True


def endpoint(base_url: str) -> str:
    value = base_url.rstrip("/")
    return value if value.endswith("/chat/completions") else value + "/chat/completions"


def api_key(base_url: str) -> str:
    hostname = (urlparse(base_url).hostname or "").lower()
    if hostname.endswith("nimabo.io"):
        names = ("NIMABO_API_KEY", "OPENAI_API_KEY", "SOGENPORT_API_KEY")
    elif hostname.endswith("sogenport.com"):
        names = ("SOGENPORT_API_KEY", "OPENAI_API_KEY", "NIMABO_API_KEY")
    else:
        names = ("OPENAI_API_KEY", "NIMABO_API_KEY", "SOGENPORT_API_KEY")

    for name in names:
        value = os.getenv(name, "").strip()
        if value and value not in API_KEY_PLACEHOLDERS:
            return value
    value = getpass.getpass("OpenAI-compatible API key (input hidden): ").strip()
    if not value:
        raise SystemExit("An API key is required.")
    return value


def retry_api_timeouts(
    timeout_seconds: int,
    attempts: int,
    label: str,
) -> Callable[[Any], None]:
    def register(agent: Any) -> None:
        original_request = agent.model._request_openai

        def request_openai(messages: dict, timeout: int):
            global API_TIMEOUT_EVENT_COUNT

            effective_timeout = min(timeout, timeout_seconds)
            for attempt in range(1, attempts + 1):
                started = time.monotonic()
                try:
                    return original_request(messages, effective_timeout)
                except TRANSIENT_API_ERRORS as error:
                    API_TIMEOUT_EVENT_COUNT += 1
                    elapsed = round(time.monotonic() - started, 2)
                    will_retry = attempt < attempts
                    print(
                        f"{label}_API_TRANSPORT_ERROR "
                        f"kind={type(error).__name__} "
                        f"attempt={attempt}/{attempts} "
                        f"elapsed={elapsed}s retry={str(will_retry).lower()}",
                        flush=True,
                    )
                    if not will_retry:
                        raise

        agent.model._request_openai = request_openai

    return register


def task_dir(app: str) -> Path:
    return REPO_ROOT / "tasks" / "VM" / APP_CONFIGS[app].task_dir


def available_tasks(app: str) -> list[str]:
    return [path.stem for path in sorted(task_dir(app).glob("*.json"))]


def selected_tasks(args: argparse.Namespace) -> tuple[str, ...]:
    tasks = tuple(args.task or available_tasks(args.app))
    known = set(available_tasks(args.app))
    unknown = [task for task in tasks if task not in known]
    if unknown:
        raise SystemExit(
            f"Unknown {args.app} task(s): {', '.join(unknown)}. "
            f"Known tasks: {', '.join(sorted(known))}"
        )
    if args.limit is not None:
        if args.limit <= 0:
            raise SystemExit("--limit must be positive.")
        tasks = tasks[: args.limit]
    return tasks


def safe_path_part(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._+-]+", "-", value).strip("-") or "run"


def validate_vm_runtime() -> str:
    try:
        import desktop_env  # noqa: F401
    except ModuleNotFoundError:
        from sci.vm.desktop_env_fallback import DesktopEnv  # noqa: F401

        return "bundled VMware compatibility adapter"
    return "desktop-env"


def validate_vmware(vm_path: Path, vmware_bin: Path) -> Path:
    vm_path = vm_path.expanduser().resolve()
    if not vm_path.is_file():
        raise SystemExit(f"VMware configuration not found: {vm_path}")

    vmrun = (vmware_bin.expanduser().resolve() / "vmrun.exe")
    if not vmrun.is_file():
        raise SystemExit(f"vmrun.exe not found: {vmrun}")

    os.environ["PATH"] = str(vmrun.parent) + os.pathsep + os.environ.get("PATH", "")
    return vmrun


def validate_snapshot(vmrun: Path, vm_path: Path, snapshot: str) -> None:
    try:
        result = subprocess.run(
            [str(vmrun), "-T", "ws", "listSnapshots", str(vm_path)],
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
    except subprocess.TimeoutExpired as error:
        raise SystemExit("Timed out while listing VMware snapshots.") from error

    if result.returncode != 0:
        raise SystemExit("Unable to list VMware snapshots: " + result.stderr.strip())
    if snapshot not in result.stdout.splitlines():
        raise SystemExit(
            f"VMware snapshot {snapshot!r} was not found for {vm_path}."
        )


def obs_types(obs: str) -> set[Any]:
    _, _, _, OBS, _ = import_scienceboard()
    choices = {
        "screenshot": {OBS.screenshot},
        "a11y_tree": {OBS.a11y_tree},
        "screenshot+a11y_tree": {OBS.screenshot, OBS.a11y_tree},
        "set_of_marks": {OBS.set_of_marks},
    }
    return choices[obs]


def prepare_task_definition(
    app: str,
    task_id: str,
    snapshot: str | None,
    attempt_root: Path,
) -> Path:
    source_path = task_dir(app) / f"{task_id}.json"
    if app != "TeXstudio" or snapshot is None:
        return source_path

    config = json.loads(source_path.read_text(encoding="utf-8"))
    if config.get("snapshot") == snapshot:
        return source_path

    runtime_dir = attempt_root / "runtime-task-definitions"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    runtime_path = runtime_dir / source_path.name
    config["snapshot"] = snapshot
    runtime_path.write_text(
        json.dumps(config, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return runtime_path


def task_config(app: str, task_id: str) -> dict[str, Any]:
    config_path = task_dir(app) / f"{task_id}.json"
    return json.loads(config_path.read_text(encoding="utf-8"))


def external_network_requirements(app: str, task_id: str) -> list[dict[str, Any]]:
    requirements = task_config(app, task_id).get("requirements", {})
    if not isinstance(requirements, dict):
        return []
    external_network = requirements.get("external_network", [])
    if not isinstance(external_network, list):
        return []
    return [item for item in external_network if isinstance(item, dict)]


def should_skip_if_unavailable(requirement: dict[str, Any]) -> bool:
    value = requirement.get("skip_if_unavailable", True)
    return bool(value)


def shell_single_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def start_vm_for_preflight(vmrun: Path, vm_path: Path, headless: bool) -> tuple[bool, str]:
    command = [str(vmrun), "-T", "ws", "start", str(vm_path)]
    if headless:
        command.append("nogui")
    try:
        started = subprocess.run(
            command,
            text=True,
            capture_output=True,
            check=False,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        return False, "vmrun start timed out during preflight"
    if started.returncode != 0 and _is_target_vm_listed(vmrun, vm_path) is not True:
        detail = (started.stderr or started.stdout).strip()
        return False, f"vmrun start failed during preflight: {detail}"
    return True, "started"


def wait_for_vm_preflight_service(
    vmrun: Path,
    vm_path: Path,
    timeout_seconds: float = 300.0,
) -> tuple[str | None, str]:
    deadline = time.monotonic() + timeout_seconds
    vm_ip: str | None = None
    while time.monotonic() < deadline:
        try:
            ip_result = subprocess.run(
                [str(vmrun), "-T", "ws", "getGuestIPAddress", str(vm_path)],
                text=True,
                capture_output=True,
                check=False,
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            time.sleep(3)
            continue
        if ip_result.returncode == 0 and ip_result.stdout.strip():
            vm_ip = ip_result.stdout.strip().split(":")[0]
            break
        time.sleep(3)

    if not vm_ip:
        return None, "could not obtain VM guest IP during preflight"

    service_url = f"http://{vm_ip}:5000/setup/execute"
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            response = requests.post(
                service_url,
                json={"command": ["bash", "-lc", "true"], "shell": False},
                timeout=10,
            )
            if response.status_code == 200:
                return vm_ip, "ready"
        except requests.RequestException:
            pass
        time.sleep(3)

    return vm_ip, "VM guest preflight service did not become ready"


def run_vm_execute(vm_ip: str, command: str, timeout_seconds: int) -> dict[str, Any]:
    response = requests.post(
        f"http://{vm_ip}:5000/setup/execute",
        json={"command": ["bash", "-lc", command], "shell": False},
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, dict) else {"raw": payload}


def external_network_preflight(
    args: argparse.Namespace,
    task_id: str,
    task_root: Path,
    vmrun: Path,
    vm_path: Path,
) -> tuple[bool, str | None]:
    requirements = external_network_requirements(args.app, task_id)
    if not requirements:
        return True, None

    task_root.mkdir(parents=True, exist_ok=True)
    preflight_path = task_root / "preflight-external-network.json"
    proxy = os.getenv("SCIENCEBOARD_VM_PROXY", "").strip()
    records: list[dict[str, Any]] = []

    started, start_detail = start_vm_for_preflight(vmrun, vm_path, args.headless)
    if not started:
        reason = start_detail
        preflight_path.write_text(
            json.dumps(
                {
                    "task_id": task_id,
                    "status": "failed",
                    "reason": reason,
                    "requirements": requirements,
                    "proxy_configured": bool(proxy),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return False, reason

    vm_ip, ready_detail = wait_for_vm_preflight_service(vmrun, vm_path)
    if vm_ip is None:
        reason = ready_detail
        preflight_path.write_text(
            json.dumps(
                {
                    "task_id": task_id,
                    "status": "failed",
                    "reason": reason,
                    "requirements": requirements,
                    "proxy_configured": bool(proxy),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return False, reason

    for requirement in requirements:
        name = str(requirement.get("name", "external network"))
        url = str(requirement.get("url", "")).strip()
        if not url:
            records.append(
                {
                    "name": name,
                    "status": "failed",
                    "reason": "missing requirement url",
                }
            )
            continue

        connect_timeout = int(
            requirement.get(
                "connect_timeout", DEFAULT_EXTERNAL_NETWORK_CONNECT_TIMEOUT
            )
        )
        max_time = int(requirement.get("timeout", DEFAULT_EXTERNAL_NETWORK_TIMEOUT))
        output_file = f"/tmp/scienceboard-preflight-{safe_path_part(task_id)}.out"
        curl_parts = [
            "curl",
            "-L",
            "-sS",
            "--connect-timeout",
            str(connect_timeout),
            "--max-time",
            str(max_time),
        ]
        if proxy:
            curl_parts.extend(["-x", proxy])
        curl_parts.extend(
            [
                "-o",
                output_file,
                "-w",
                "HTTP_CODE=%{http_code}\\nEFFECTIVE_URL=%{url_effective}\\nTIME_TOTAL=%{time_total}\\n",
                url,
            ]
        )
        command = " ".join(shlex.quote(part) for part in curl_parts)
        command += (
            f"; rc=$?; if test -f {shell_single_quote(output_file)}; "
            f"then bytes=$(wc -c < {shell_single_quote(output_file)}); "
            "else bytes=0; fi; "
            'echo "EXIT_CODE=$rc"; echo "BODY_BYTES=$bytes"; exit 0'
        )

        try:
            payload = run_vm_execute(vm_ip, command, max(max_time + 20, 60))
        except Exception as error:
            records.append(
                {
                    "name": name,
                    "url": url,
                    "status": "failed",
                    "reason": f"{type(error).__name__}: {error}",
                    "proxy_configured": bool(proxy),
                }
            )
            continue

        output = str(payload.get("output", ""))
        parsed: dict[str, str] = {}
        for raw_line in output.splitlines():
            key, separator, value = raw_line.partition("=")
            if separator:
                parsed[key.strip()] = value.strip()
        exit_code = int(parsed.get("EXIT_CODE", "-1"))
        http_code = parsed.get("HTTP_CODE", "000")
        body_bytes = int(parsed.get("BODY_BYTES", "0").split()[0])
        ok = exit_code == 0 and http_code.isdigit() and 200 <= int(http_code) < 400 and body_bytes > 0
        records.append(
            {
                "name": name,
                "url": url,
                "status": "passed" if ok else "failed",
                "curl_exit_code": exit_code,
                "http_code": http_code,
                "effective_url": parsed.get("EFFECTIVE_URL"),
                "time_total": parsed.get("TIME_TOTAL"),
                "body_bytes": body_bytes,
                "proxy_configured": bool(proxy),
                "vm_ip": vm_ip,
                "guest_returncode": payload.get("returncode"),
                "guest_error": payload.get("error"),
            }
        )

    failed_records = [record for record in records if record.get("status") != "passed"]
    status = "passed" if not failed_records else "failed"
    preflight_path.write_text(
        json.dumps(
            {
                "task_id": task_id,
                "status": status,
                "proxy_configured": bool(proxy),
                "requirements": requirements,
                "checks": records,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    if failed_records and any(should_skip_if_unavailable(item) for item in requirements):
        first = failed_records[0]
        reason = (
            f"external network preflight failed for {first.get('name')}: "
            f"{first.get('url')} "
            f"(curl_exit_code={first.get('curl_exit_code')}, "
            f"http_code={first.get('http_code')}, "
            f"proxy_configured={str(bool(proxy)).lower()})"
        )
        return False, reason
    return True, None


def install_texstudio_chimerax_readiness_wrapper(
    timeout_seconds: float,
    poll_interval_seconds: float,
) -> None:
    """Retry only transient ChimeraX REST startup failures in TeXstudio tasks."""
    from sci.TeXstudio.texstudio import VMManager as TeXstudioVMManager
    from sci.vm.vmanager import VManager

    if getattr(TeXstudioVMManager, "_scienceboard_chimerax_readiness_wrapper", False):
        return

    def chimerax_execute_with_readiness(
        self: TeXstudioVMManager,
        command: str,
    ) -> bool:
        deadline = time.monotonic() + timeout_seconds
        attempts = 0
        last_failure = "endpoint did not return a valid response"

        while True:
            attempts += 1
            try:
                response = self._request(
                    f"POST:{VManager.SERVER_PORT}/chimerax/run",
                    param={"json": {"command": command}},
                )
                if response.status_code == 200:
                    payload = response.json()
                    if isinstance(payload, dict) and "error" in payload:
                        if payload["error"] is None:
                            if attempts > 1:
                                print(
                                    "ChimeraX REST became ready after "
                                    f"{attempts} probes for {command!r}.",
                                    flush=True,
                                )
                            return True
                        return False
                    last_failure = "HTTP 200 response lacked an error field"
                else:
                    last_failure = f"HTTP {response.status_code}"
            except Exception as error:
                last_failure = f"{type(error).__name__}: {error}"

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError(
                    "ChimeraX REST endpoint was not ready within "
                    f"{timeout_seconds:g}s after {attempts} probes; "
                    f"last failure: {last_failure}."
                )
            if attempts == 1 or attempts % 5 == 0:
                print(
                    "Waiting for ChimeraX REST readiness "
                    f"({last_failure}; probe {attempts}).",
                    flush=True,
                )
            time.sleep(min(poll_interval_seconds, remaining))

    TeXstudioVMManager._chimerax_execute = chimerax_execute_with_readiness
    TeXstudioVMManager._scienceboard_chimerax_readiness_wrapper = True


def install_headless_recording_compatibility() -> None:
    """Skip optional video recording for controllers without that API."""
    from sci.vm.vmanager import VManager

    if getattr(VManager, "_scienceboard_recording_compatibility", False):
        return

    original_record_start = VManager.record_start
    original_record_stop = VManager.record_stop

    def supports_recording(manager: VManager) -> bool:
        controller = manager.controller
        return bool(
            controller is not None
            and hasattr(controller, "start_recording")
            and hasattr(controller, "end_recording")
        )

    def record_start(manager: VManager) -> None:
        if not supports_recording(manager):
            manager.vlog.warning(
                "Controller has no video-recording API; "
                "continuing with per-step screenshots and observations."
            )
            return
        original_record_start(manager)

    def record_stop(manager: VManager, dest_path: str) -> None:
        if not supports_recording(manager):
            return
        original_record_stop(manager, dest_path)

    VManager.record_start = record_start
    VManager.record_stop = record_stop
    VManager._scienceboard_recording_compatibility = True
    VManager._scienceboard_headless_recording_compatibility = True


def install_headless_a11y_timeout_compatibility(timeout_seconds: float) -> None:
    """Allow the repaired TeXstudio AT-SPI endpoint to finish in headless VMs."""
    import requests

    from sci.vm.desktop_env_fallback import PythonController

    if getattr(PythonController, "_scienceboard_headless_a11y_timeout", False):
        return

    original_get = PythonController._get

    def get_with_a11y_timeout(controller: PythonController, route: str):
        if route != "/accessibility":
            return original_get(controller, route)

        for _ in range(3):
            try:
                response = requests.get(
                    controller.http_server + route,
                    timeout=timeout_seconds,
                )
                if response.status_code == 200:
                    return response
            except requests.RequestException:
                pass
            time.sleep(3)
        return None

    PythonController._get = get_with_a11y_timeout
    PythonController._scienceboard_headless_a11y_timeout = True


def install_empty_a11y_tree_fallback_compatibility() -> None:
    """Prevent transient empty AT-SPI output from becoming a skipped task."""
    from sci.vm.vmanager import VManager

    if getattr(VManager, "_scienceboard_empty_a11y_tree_fallback", False):
        return

    original_a11y_tree = VManager.a11y_tree

    def a11y_tree_with_empty_fallback(manager: VManager) -> str:
        try:
            return original_a11y_tree(manager)
        except AssertionError:
            manager.vlog.warning(
                "Accessibility tree remained empty after retries; "
                "using empty-tree fallback observation."
            )
            return EMPTY_A11Y_TREE_FALLBACK

    VManager.a11y_tree = a11y_tree_with_empty_fallback
    VManager._scienceboard_empty_a11y_tree_fallback = True


def latest_result(root: Path) -> str | None:
    candidates = [path for path in root.rglob("result.out") if path.is_file()]
    if not candidates:
        return None
    value = max(candidates, key=lambda path: path.stat().st_mtime).read_text(
        encoding="utf-8"
    ).strip()
    return value if value in {"0", "1"} else None


def newest_mtime(root: Path) -> float:
    if not root.exists():
        return 0.0
    candidates = [root]
    candidates.extend(path for path in root.rglob("*") if path.is_file())
    return max(path.stat().st_mtime for path in candidates)


def tail_text(path: Path, line_count: int = 12) -> str:
    if not path.is_file():
        return ""
    return "\n".join(
        path.read_text(encoding="utf-8", errors="replace").splitlines()[-line_count:]
    )


def write_state(
    path: Path,
    *,
    status: str,
    tasks: tuple[str, ...],
    completed: list[str],
    skipped: list[dict[str, Any]],
    outcomes: dict[str, str],
    current_task: str | None,
    current_attempt: int | None,
    args: argparse.Namespace,
    vm_path: Path,
    error: BaseException | None = None,
) -> None:
    config = {
        "app": args.app,
        "model": args.model,
        "reason_effort": args.reason_effort,
        "observation": args.obs,
        "visible": not args.headless,
        "headless": args.headless,
        "vm_path": str(vm_path),
        "vmware_bin": str(args.vmware_bin),
        "no_progress_timeout_seconds": args.no_progress_timeout,
        "task_timeout_seconds": args.task_timeout,
        "infrastructure_retries": args.infrastructure_retries,
        "api_timeout_seconds": args.api_timeout,
        "api_timeout_attempts": args.api_timeout_attempts,
        "excel_writes_during_run": False,
        "vm_proxy_configured": bool(os.getenv("SCIENCEBOARD_VM_PROXY", "").strip()),
    }
    if args.snapshot is not None:
        config["snapshot"] = args.snapshot
    if "a11y_tree" in args.obs or args.obs == "set_of_marks":
        config["a11y_request_timeout_seconds"] = args.headless_a11y_request_timeout
    if args.app == "TeXstudio":
        config.update(
            {
                "chimerax_ready_timeout_seconds": args.chimerax_ready_timeout,
                "chimerax_ready_poll_interval_seconds": args.chimerax_ready_poll_interval,
            }
        )

    payload: dict[str, Any] = {
        "pid": os.getpid(),
        "updated_at": datetime.now().astimezone().isoformat(),
        "status": status,
        "current_task": current_task,
        "current_attempt": current_attempt,
        "tasks": list(tasks),
        "completed_tasks": completed,
        "skipped_infrastructure": skipped,
        "outcomes": outcomes,
        "config": config,
    }
    if error is not None:
        payload["error"] = f"{type(error).__name__}: {error}"

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    replace_with_retry(temporary, path)


def _normalize_vmx_path(value: str | Path) -> str:
    return os.path.normcase(os.path.normpath(str(value).strip().strip('"')))


def _listed_vms(vmrun: Path, timeout: int = 15) -> list[str] | None:
    try:
        listed = subprocess.run(
            [str(vmrun), "-T", "ws", "list"],
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return None
    return [
        line.strip()
        for line in listed.stdout.splitlines()
        if line.strip().lower().endswith(".vmx")
    ]


def _is_target_vm_listed(vmrun: Path, vm_path: Path) -> bool | None:
    listed = _listed_vms(vmrun)
    if listed is None:
        return None
    target = _normalize_vmx_path(vm_path)
    return any(_normalize_vmx_path(line) == target for line in listed)


def _kill_vmware_vmx_process_for_path(vm_path: Path) -> list[int]:
    if os.name != "nt":
        return []
    script = r"""
$target = [System.IO.Path]::GetFullPath($args[0])
$matched = Get-CimInstance Win32_Process | Where-Object {
  $_.Name -like 'vmware-vmx*' -and
  $_.CommandLine -and
  $_.CommandLine.IndexOf($target, [System.StringComparison]::OrdinalIgnoreCase) -ge 0
}
foreach ($process in $matched) {
  Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
  [Console]::Out.WriteLine($process.ProcessId)
}
"""
    try:
        killed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
                str(vm_path),
            ],
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    pids: list[int] = []
    for line in killed.stdout.splitlines():
        line = line.strip()
        if line.isdigit():
            pids.append(int(line))
    return pids


def stop_target_vm(vmrun: Path, vm_path: Path) -> bool:
    target = str(vm_path)
    listed_before = _is_target_vm_listed(vmrun, vm_path)
    if listed_before is False:
        killed_pids = _kill_vmware_vmx_process_for_path(vm_path)
        if killed_pids:
            print(
                f"VM_CLEANUP killed unlisted vmware-vmx "
                f"pids={','.join(map(str, killed_pids))} vm={target}",
                flush=True,
            )
            time.sleep(5)
        return True

    try:
        stopped = subprocess.run(
            [str(vmrun), "-T", "ws", "stop", target, "hard"],
            text=True,
            capture_output=True,
            check=False,
            timeout=45,
        )
        if stopped.returncode != 0:
            print(
                f"VM_CLEANUP vmrun_stop_returncode={stopped.returncode} "
                f"vm={target}",
                flush=True,
            )
    except subprocess.TimeoutExpired:
        print(f"VM_CLEANUP vmrun_stop_timeout vm={target}", flush=True)

    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        listed_now = _is_target_vm_listed(vmrun, vm_path)
        if listed_now is False:
            return True
        time.sleep(2)

    killed_pids = _kill_vmware_vmx_process_for_path(vm_path)
    if killed_pids:
        print(
            f"VM_CLEANUP killed vmware-vmx pids={','.join(map(str, killed_pids))} "
            f"vm={target}",
            flush=True,
        )
        time.sleep(5)

    listed_after = _is_target_vm_listed(vmrun, vm_path)
    if listed_after is False:
        return True
    if listed_after is None and killed_pids:
        return True
    print(f"VM_CLEANUP unable_to_confirm_stopped vm={target}", flush=True)
    return False


def terminate_worker_tree(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                text=True,
                capture_output=True,
                check=False,
                timeout=30,
            )
            return
        except subprocess.TimeoutExpired:
            pass
    process.terminate()


def worker_command(
    args: argparse.Namespace,
    task_id: str,
    attempt_root: Path,
) -> list[str]:
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--worker",
        "--app",
        args.app,
        "--task",
        task_id,
        "--model",
        args.model,
        "--reason-effort",
        args.reason_effort,
        "--base-url",
        args.base_url,
        "--vm-path",
        str(args.vm_path),
        "--vmware-bin",
        str(args.vmware_bin),
        "--logs-path",
        str(attempt_root),
        "--obs",
        args.obs,
        "--chimerax-ready-timeout",
        str(args.chimerax_ready_timeout),
        "--chimerax-ready-poll-interval",
        str(args.chimerax_ready_poll_interval),
        "--headless-a11y-request-timeout",
        str(args.headless_a11y_request_timeout),
        "--api-timeout",
        str(args.api_timeout),
        "--api-timeout-attempts",
        str(args.api_timeout_attempts),
    ]
    if args.snapshot is not None:
        command.extend(["--snapshot", args.snapshot])
    if args.headless:
        command.append("--headless")
    return command


def run_worker(args: argparse.Namespace) -> None:
    load_local_env()
    validate_vm_runtime()
    install_headless_recording_compatibility()
    vm_path = args.vm_path.expanduser().resolve()
    validate_vmware(vm_path, args.vmware_bin)

    if "a11y_tree" in args.obs or args.obs == "set_of_marks":
        install_headless_a11y_timeout_compatibility(
            args.headless_a11y_request_timeout,
        )
        install_empty_a11y_tree_fallback_compatibility()

    if args.app == "TeXstudio":
        if args.snapshot is None:
            raise SystemExit("TeXstudio requires --snapshot.")
        install_texstudio_chimerax_readiness_wrapper(
            args.chimerax_ready_timeout,
            args.chimerax_ready_poll_interval,
        )

    if len(args.task or ()) != 1:
        raise SystemExit("Worker mode requires exactly one --task.")
    if args.logs_path is None:
        raise SystemExit("Worker mode requires --logs-path.")
    task_id = args.task[0]
    attempt_root = args.logs_path.expanduser().resolve()
    task_log_root = attempt_root / task_id
    task_definition = prepare_task_definition(
        args.app,
        task_id,
        args.snapshot,
        attempt_root,
    )

    AIOAgent, AllInOne, Automata, _, Tester = import_scienceboard()
    model = Automata(
        register=[retry_api_timeouts(
            args.api_timeout,
            args.api_timeout_attempts,
            "BASELINE",
        )],
        model_style="openai",
        base_url=endpoint(args.base_url),
        model_name=args.model,
        api_key=api_key(args.base_url),
        max_tokens=None,
        top_p=None,
        temperature=None,
        reason_effort=args.reason_effort,
        overflow_style="openai_gpt",
    )(AIOAgent)
    community = AllInOne(model)

    print(f"Worker app: {args.app}", flush=True)
    print(f"Worker task: {task_id}", flush=True)
    print(f"Worker task definition: {task_definition}", flush=True)
    print(f"Worker logs: {task_log_root}", flush=True)
    Tester(
        tasks_path=str(task_definition),
        logs_path=str(task_log_root),
        community=community,
        vm_path=str(vm_path),
        obs_types=obs_types(args.obs),
        headless=args.headless,
        ignore=False,
    )()


def run_attempt(
    args: argparse.Namespace,
    task_id: str,
    attempt_root: Path,
    attempt: int,
    vmrun: Path,
    vm_path: Path,
    state_path: Path,
    tasks: tuple[str, ...],
    completed: list[str],
    skipped: list[dict[str, Any]],
    outcomes: dict[str, str],
) -> tuple[str, str]:
    attempt_root.mkdir(parents=True, exist_ok=True)
    stdout_path = attempt_root / "worker.out.log"
    stderr_path = attempt_root / "worker.err.log"
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    write_state(
        state_path,
        status="running",
        tasks=tasks,
        completed=completed,
        skipped=skipped,
        outcomes=outcomes,
        current_task=task_id,
        current_attempt=attempt,
        args=args,
        vm_path=vm_path,
    )

    with stdout_path.open("w", encoding="utf-8") as stdout, stderr_path.open(
        "w", encoding="utf-8"
    ) as stderr:
        process = subprocess.Popen(
            worker_command(args, task_id, attempt_root),
            cwd=REPO_ROOT,
            stdout=stdout,
            stderr=stderr,
            creationflags=creationflags,
        )
        started_at = time.monotonic()
        last_progress_at = started_at
        last_mtime = newest_mtime(attempt_root)
        reason = ""

        while process.poll() is None:
            time.sleep(5)
            current_mtime = newest_mtime(attempt_root)
            if current_mtime > last_mtime:
                last_mtime = current_mtime
                last_progress_at = time.monotonic()

            elapsed = time.monotonic() - started_at
            silent_for = time.monotonic() - last_progress_at
            write_state(
                state_path,
                status="running",
                tasks=tasks,
                completed=completed,
                skipped=skipped,
                outcomes=outcomes,
                current_task=task_id,
                current_attempt=attempt,
                args=args,
                vm_path=vm_path,
            )
            if silent_for > args.no_progress_timeout:
                reason = f"no log progress for {int(silent_for)} seconds"
                terminate_worker_tree(process)
                break
            if elapsed > args.task_timeout:
                reason = f"task watchdog exceeded {args.task_timeout} seconds"
                terminate_worker_tree(process)
                break

        try:
            exit_code = process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            process.kill()
            exit_code = process.wait(timeout=20)
            reason = reason or "worker did not terminate after watchdog request"

    result = latest_result(attempt_root)
    if result is not None:
        return ("completed", result)

    stop_target_vm(vmrun, vm_path)
    detail = reason or f"worker exited with code {exit_code} without evaluator result"
    if tail_text(stderr_path):
        detail += "; worker stderr retained in worker.err.log"
    return ("infrastructure", detail)


def run_one_task(
    args: argparse.Namespace,
    task_id: str,
    task_root: Path,
    vmrun: Path,
    vm_path: Path,
    state_path: Path,
    tasks: tuple[str, ...],
    completed: list[str],
    skipped: list[dict[str, Any]],
    outcomes: dict[str, str],
) -> tuple[str, str]:
    preflight_ok, preflight_reason = external_network_preflight(
        args,
        task_id,
        task_root,
        vmrun,
        vm_path,
    )
    if not preflight_ok:
        stop_target_vm(vmrun, vm_path)
        return ("infrastructure_skip", preflight_reason or "external network preflight failed")

    total_attempts = args.infrastructure_retries + 1
    last_detail = ""
    for attempt in range(1, total_attempts + 1):
        if attempt > 1:
            print(
                f"{task_id}: retrying infrastructure attempt "
                f"{attempt}/{total_attempts}",
                flush=True,
            )
            stop_target_vm(vmrun, vm_path)
        status, detail = run_attempt(
            args,
            task_id,
            task_root / f"attempt-{attempt}",
            attempt,
            vmrun,
            vm_path,
            state_path,
            tasks,
            completed,
            skipped,
            outcomes,
        )
        if status == "completed":
            return (status, detail)
        last_detail = detail
    return ("infrastructure_skip", last_detail)


def default_run_name(args: argparse.Namespace, tasks: tuple[str, ...]) -> str:
    config = APP_CONFIGS[args.app]
    pieces = [
        f"{config.log_slug}-supervised-{len(tasks)}-baseline",
        safe_path_part(args.model),
        safe_path_part(args.reason_effort),
        safe_path_part(args.obs),
    ]
    if args.snapshot is not None:
        pieces.append(safe_path_part(args.snapshot))
    pieces.extend(
        [
            "headless" if args.headless else "visible",
            datetime.now().strftime("%Y%m%d-%H%M%S"),
        ]
    )
    return "-".join(pieces)


def run_supervisor(args: argparse.Namespace) -> None:
    local_env_loaded = load_local_env()
    runtime_name = validate_vm_runtime()

    if args.no_progress_timeout <= 0 or args.task_timeout <= 0:
        raise SystemExit("Watchdog values must be positive.")
    if args.infrastructure_retries < 0:
        raise SystemExit("--infrastructure-retries cannot be negative.")
    if args.api_timeout <= 0 or args.api_timeout_attempts <= 0:
        raise SystemExit("API timeout values must be positive.")
    if args.chimerax_ready_timeout <= 0 or args.chimerax_ready_poll_interval <= 0:
        raise SystemExit("ChimeraX readiness timeout and poll interval must be positive.")
    if args.headless_a11y_request_timeout <= 0:
        raise SystemExit("Headless a11y request timeout must be positive.")

    tasks = selected_tasks(args)
    vm_path = args.vm_path.expanduser().resolve()
    vmrun = validate_vmware(vm_path, args.vmware_bin)
    if args.app == "TeXstudio" and args.snapshot is not None:
        validate_snapshot(vmrun, vm_path, args.snapshot)

    run_root = (
        args.logs_path
        or REPO_ROOT / "logs" / "reproduction" / default_run_name(args, tasks)
    )
    run_root = run_root.expanduser().resolve()
    state_path = run_root / "run-state.json"

    print(f"App: {args.app}")
    print(f"Model: {args.model}")
    print(f"Endpoint: {endpoint(args.base_url)}")
    print(f"Reasoning effort: {args.reason_effort}")
    print(f"Observation: {args.obs}")
    print(f"VMware mode: {'headless' if args.headless else 'visible'}")
    print(f"VM runtime: {runtime_name}")
    print(f"VM: {vm_path}")
    print(f"vmrun: {vmrun}")
    if args.snapshot is not None:
        print(f"Task snapshot: {args.snapshot}")
    print(f"Tasks ({len(tasks)}): {', '.join(tasks)}")
    print(f"No-progress watchdog: {args.no_progress_timeout}s")
    print(f"Absolute task watchdog: {args.task_timeout}s")
    print(f"Infrastructure retries: {args.infrastructure_retries}")
    print(
        f"API timeout: {args.api_timeout}s, "
        f"attempts: {args.api_timeout_attempts}"
    )
    if "a11y_tree" in args.obs or args.obs == "set_of_marks":
        print(f"A11y request timeout: {args.headless_a11y_request_timeout:g}s")
    if args.app == "TeXstudio":
        print(
            "ChimeraX readiness wrapper: "
            f"{args.chimerax_ready_timeout:g}s timeout, "
            f"{args.chimerax_ready_poll_interval:g}s polling"
        )
    print("Excel writes during run: disabled")
    print(f"Logs: {run_root}")
    print(f"Local config: {'loaded' if local_env_loaded else 'not found'}")
    if not args.run:
        print("Configuration validated. Add --run to execute.")
        return

    completed: list[str] = []
    skipped: list[dict[str, Any]] = []
    outcomes: dict[str, str] = {}
    current_task: str | None = None
    current_attempt: int | None = None
    write_state(
        state_path,
        status="running",
        tasks=tasks,
        completed=completed,
        skipped=skipped,
        outcomes=outcomes,
        current_task=current_task,
        current_attempt=current_attempt,
        args=args,
        vm_path=vm_path,
    )

    try:
        for task_id in tasks:
            current_task = task_id
            print(f"Starting task: {task_id}", flush=True)
            task_status, detail = run_one_task(
                args,
                task_id,
                run_root / task_id,
                vmrun,
                vm_path,
                state_path,
                tasks,
                completed,
                skipped,
                outcomes,
            )
            if task_status == "completed":
                completed.append(task_id)
                outcomes[task_id] = "passed" if detail == "1" else "failed"
                print(f"{task_id}: evaluator result {detail}", flush=True)
            else:
                skipped.append({"task_id": task_id, "reason": detail})
                outcomes[task_id] = "infrastructure_skip"
                print(f"{task_id}: infrastructure skip ({detail})", flush=True)
            current_task = None
            current_attempt = None
            write_state(
                state_path,
                status="running",
                tasks=tasks,
                completed=completed,
                skipped=skipped,
                outcomes=outcomes,
                current_task=current_task,
                current_attempt=current_attempt,
                args=args,
                vm_path=vm_path,
            )
    except BaseException as error:
        stop_target_vm(vmrun, vm_path)
        write_state(
            state_path,
            status="failed",
            tasks=tasks,
            completed=completed,
            skipped=skipped,
            outcomes=outcomes,
            current_task=current_task,
            current_attempt=current_attempt,
            args=args,
            vm_path=vm_path,
            error=error,
        )
        raise
    else:
        write_state(
            state_path,
            status="completed",
            tasks=tasks,
            completed=completed,
            skipped=skipped,
            outcomes=outcomes,
            current_task=None,
            current_attempt=None,
            args=args,
            vm_path=vm_path,
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run ScienceBoard VM app baselines under a supervised watchdog."
    )
    parser.add_argument("--app", required=True, choices=sorted(APP_CONFIGS))
    parser.add_argument(
        "--task",
        action="append",
        help="Task id to run; repeat for multiple tasks. Defaults to all app tasks.",
    )
    parser.add_argument("--limit", type=int)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--reason-effort", default=DEFAULT_REASON_EFFORT)
    parser.add_argument(
        "--base-url",
        default=os.getenv("SCIENCEBOARD_BASE_URL", DEFAULT_BASE_URL),
    )
    parser.add_argument(
        "--vm-path",
        type=Path,
        default=Path(os.getenv("VM_PATH", str(DEFAULT_VM))),
    )
    parser.add_argument(
        "--vmware-bin",
        type=Path,
        default=Path(os.getenv("VMWARE_BIN", str(DEFAULT_VMWARE_BIN))),
    )
    parser.add_argument(
        "--logs-path",
        type=Path,
        help="Supervisor run root, or worker attempt root in --worker mode.",
    )
    parser.add_argument(
        "--obs",
        choices=("screenshot", "a11y_tree", "screenshot+a11y_tree", "set_of_marks"),
        default="screenshot+a11y_tree",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run VMware without showing its host window. Default is visible.",
    )
    parser.add_argument(
        "--snapshot",
        help="Task snapshot override. Defaults only for apps that require it.",
    )
    parser.add_argument(
        "--no-progress-timeout",
        type=int,
        default=DEFAULT_NO_PROGRESS_TIMEOUT,
    )
    parser.add_argument("--task-timeout", type=int, default=DEFAULT_TASK_TIMEOUT)
    parser.add_argument(
        "--infrastructure-retries",
        type=int,
        default=DEFAULT_INFRASTRUCTURE_RETRIES,
        help="Additional attempts after a worker ends without evaluator result.",
    )
    parser.add_argument("--api-timeout", type=int, default=DEFAULT_API_TIMEOUT)
    parser.add_argument(
        "--api-timeout-attempts",
        type=int,
        default=DEFAULT_API_TIMEOUT_ATTEMPTS,
    )
    parser.add_argument(
        "--chimerax-ready-timeout",
        type=float,
        default=DEFAULT_CHIMERAX_READY_TIMEOUT,
    )
    parser.add_argument(
        "--chimerax-ready-poll-interval",
        type=float,
        default=DEFAULT_CHIMERAX_READY_POLL_INTERVAL,
    )
    parser.add_argument(
        "--headless-a11y-request-timeout",
        type=float,
        default=DEFAULT_HEADLESS_A11Y_REQUEST_TIMEOUT,
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    return parser


def main() -> None:
    load_local_env()
    args = build_parser().parse_args()
    default_snapshot = APP_CONFIGS[args.app].default_snapshot
    if args.snapshot is None and default_snapshot is not None:
        args.snapshot = default_snapshot

    if args.worker:
        run_worker(args)
    else:
        run_supervisor(args)


if __name__ == "__main__":
    main()
