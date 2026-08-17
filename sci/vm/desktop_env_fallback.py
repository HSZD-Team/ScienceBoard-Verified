"""Small VMware-only replacement for the subset of desktop-env ScienceBoard uses.

The upstream desktop-env 0.1.22 package pins NumPy 1.26, which cannot be
installed on the host's Python 3.14.  ScienceBoard's VM manager only needs
the lifecycle and controller surface below; its task setup and evaluators
remain in ScienceBoard itself.
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
from dataclasses import dataclass
from typing import Any, Optional

import requests


LOGGER = logging.getLogger(__name__)
VMRUN_TIMEOUT = 90
IP_TIMEOUT = 300
IP_POLL_INTERVAL = 5
READY_TIMEOUT = 180
PROGRESS_INTERVAL = 30


class PythonController:
    """Controller compatible with the OSWorld VM service used by ScienceBoard."""

    def __init__(self, vm_ip: str, server_port: int) -> None:
        self.vm_ip = vm_ip
        self.http_server = f"http://{vm_ip}:{server_port}"

    def _get(self, route: str) -> Optional[requests.Response]:
        for _ in range(3):
            try:
                response = requests.get(self.http_server + route, timeout=15)
                if response.status_code == 200:
                    return response
            except requests.RequestException:
                pass
            time.sleep(3)
        return None

    def get_screenshot(self) -> Optional[bytes]:
        response = self._get("/screenshot")
        return response.content if response is not None else None

    def get_accessibility_tree(self) -> Optional[str]:
        response = self._get("/accessibility")
        if response is None:
            return None
        try:
            return response.json()["AT"]
        except (ValueError, KeyError, TypeError):
            return None

    def get_terminal_output(self) -> Optional[str]:
        response = self._get("/terminal")
        if response is None:
            return None
        try:
            return response.json()["output"]
        except (ValueError, KeyError, TypeError):
            return None

    def execute_python_command(self, command: str) -> Optional[dict[str, Any]]:
        payload = {
            "command": [
                "python",
                "-c",
                "import pyautogui; import time; pyautogui.FAILSAFE = False; " + command,
            ],
            "shell": False,
        }
        for _ in range(3):
            try:
                response = requests.post(
                    self.http_server + "/execute",
                    json=payload,
                    timeout=90,
                )
                if response.status_code == 200:
                    return response.json()
            except (requests.RequestException, ValueError):
                pass
            time.sleep(3)
        return None


@dataclass
class DesktopEnv:
    """VMware lifecycle adapter with the API consumed by ``sci.vm.VManager``."""

    provider_name: str = "vmware"
    region: Optional[str] = None
    path_to_vm: Optional[str] = None
    snapshot_name: str = "sci_bench"
    action_space: str = "pyautogui"
    cache_dir: str = "cache"
    screen_size: tuple[int, int] = (1920, 1080)
    headless: bool = False
    require_a11y_tree: bool = True
    require_terminal: bool = False
    os_type: str = "Ubuntu"

    def __post_init__(self) -> None:
        if self.provider_name != "vmware":
            raise NotImplementedError("The fallback supports VMware only.")
        if not self.path_to_vm:
            raise ValueError("path_to_vm is required for the VMware fallback.")
        self.path_to_vm = os.path.abspath(os.path.expanduser(self.path_to_vm))
        self.controller: PythonController
        self._start_emulator()

    @staticmethod
    def _run_vmrun(args: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["vmrun", "-T", "ws", *args],
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout,
        )

    @staticmethod
    def _run_vmrun_quiet(
        args: list[str],
        timeout: int,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["vmrun", "-T", "ws", *args],
            text=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=timeout,
        )

    @staticmethod
    def _progress(message: str) -> None:
        print(f"SCIENCEBOARD_VM {message}", flush=True)

    def _is_running(self) -> bool:
        listed = self._run_vmrun(["list"], timeout=30)
        if listed.returncode != 0:
            raise RuntimeError(f"vmrun list failed: {listed.stderr.strip()}")
        target = os.path.normcase(os.path.normpath(self.path_to_vm))
        return any(
            os.path.normcase(os.path.normpath(line.strip())) == target
            for line in listed.stdout.splitlines()
            if line.strip()
        )

    def _guest_ip_once(self) -> Optional[str]:
        try:
            address = self._run_vmrun(
                ["getGuestIPAddress", self.path_to_vm],
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            return None

        if address.returncode != 0 or not address.stdout.strip():
            return None
        return address.stdout.strip().split(":")[0]

    def _wait_for_guest_ip(self) -> str:
        deadline = time.monotonic() + IP_TIMEOUT
        next_progress = 0.0
        while time.monotonic() < deadline:
            ip_address = self._guest_ip_once()
            if ip_address:
                self._progress(f"guest_ip_ready ip={ip_address}")
                return ip_address

            now = time.monotonic()
            if now >= next_progress:
                remaining = max(0, int(deadline - now))
                self._progress(f"guest_ip_wait remaining={remaining}s")
                next_progress = now + PROGRESS_INTERVAL
            time.sleep(IP_POLL_INTERVAL)

        raise RuntimeError("Could not obtain VM IP before timeout.")

    def _start_emulator(self) -> None:
        if not self._is_running():
            self._progress(f"start vm={self.path_to_vm}")
            start_args = ["start", self.path_to_vm]
            if self.headless:
                start_args.append("nogui")
            started = self._run_vmrun_quiet(start_args, timeout=VMRUN_TIMEOUT)
            if started.returncode != 0:
                raise RuntimeError(
                    f"vmrun start failed with code {started.returncode}."
                )
            self._progress("start_returned")
        else:
            self._progress(f"already_running vm={self.path_to_vm}")

        self.vm_ip = self._wait_for_guest_ip()
        self.controller = PythonController(self.vm_ip, 5000)
        deadline = time.monotonic() + READY_TIMEOUT
        next_progress = 0.0
        while time.monotonic() < deadline:
            now = time.monotonic()
            if now >= next_progress:
                remaining = max(0, int(deadline - now))
                self._progress(f"screenshot_wait remaining={remaining}s")
                next_progress = now + PROGRESS_INTERVAL
            if self.controller.get_screenshot() is not None:
                self._progress("screenshot_ready")
                return
            time.sleep(3)
        raise TimeoutError("VM guest service did not provide a screenshot in time.")

    def _revert_to_snapshot(self) -> None:
        self._progress(f"revert snapshot={self.snapshot_name}")
        reverted = self._run_vmrun_quiet(
            ["revertToSnapshot", self.path_to_vm, self.snapshot_name],
            timeout=VMRUN_TIMEOUT,
        )
        if reverted.returncode != 0:
            raise RuntimeError(
                "vmrun revertToSnapshot failed with code "
                f"{reverted.returncode}."
            )
        self._progress("revert_returned")

    def close(self) -> None:
        try:
            if self._is_running():
                stopped = self._run_vmrun_quiet(
                    ["stop", self.path_to_vm, "hard"],
                    timeout=VMRUN_TIMEOUT,
                )
                if stopped.returncode != 0:
                    LOGGER.warning("vmrun stop failed with code %s", stopped.returncode)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
            LOGGER.warning("Unable to stop VMware VM cleanly: %s", error)
