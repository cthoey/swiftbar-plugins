#!/usr/bin/env -S python3 -B

# <swiftbar.title>Temperature</swiftbar.title>
# <swiftbar.version>v1.0.0</swiftbar.version>
# <swiftbar.author>OpenAI Codex</swiftbar.author>
# <swiftbar.desc>Apple Silicon temperature monitor backed by iSMC.</swiftbar.desc>
# <swiftbar.refreshOnOpen>false</swiftbar.refreshOnOpen>

from __future__ import annotations

import json
import os
import shutil
import statistics
import subprocess
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve()
PLUGIN_DIR = SCRIPT_PATH.parent
REPO_ROOT = PLUGIN_DIR.parent
INSTALL_SCRIPT = REPO_ROOT / "scripts" / "install-ismc.sh"
VENDORED_HELPER = REPO_ROOT / "vendor" / "ismc" / "iSMC"
DEFAULT_PATH = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"


def helper_path() -> str | None:
    if VENDORED_HELPER.exists():
        return str(VENDORED_HELPER)

    for candidate in ("iSMC", "ismc"):
        resolved = shutil.which(candidate, path=DEFAULT_PATH)
        if resolved:
            return resolved

    return None


def helper_version(command: str) -> str | None:
    try:
        result = subprocess.run(
            [command, "version"],
            capture_output=True,
            check=True,
            env={**os.environ, "PATH": DEFAULT_PATH},
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    return result.stdout.strip() or None


def load_temperatures(command: str) -> tuple[list[dict[str, float | str]], str | None]:
    try:
        result = subprocess.run(
            [command, "temp", "-o", "json"],
            capture_output=True,
            env={**os.environ, "PATH": DEFAULT_PATH},
            text=True,
            timeout=4,
        )
    except OSError as exc:
        return [], str(exc)
    except subprocess.SubprocessError as exc:
        return [], str(exc)

    if result.returncode != 0:
        message = (result.stderr or result.stdout).strip() or f"iSMC exited with {result.returncode}"
        return [], message

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        return [], f"Unable to parse iSMC output: {exc}"

    sensors: list[dict[str, float | str]] = []
    for name, raw_value in payload.items():
        if not isinstance(raw_value, dict):
            continue

        quantity = raw_value.get("quantity")
        if quantity is None:
            continue

        try:
            numeric = float(quantity)
        except (TypeError, ValueError):
            continue

        sensors.append(
            {
                "name": name,
                "key": str(raw_value.get("key", "")),
                "value": numeric,
                "unit": str(raw_value.get("unit", "°C")),
            }
        )

    return sensors, None


def average(values: list[float]) -> float | None:
    if not values:
        return None
    return statistics.fmean(values)


def maximum(values: list[float]) -> float | None:
    if not values:
        return None
    return max(values)


def color_for(temp_c: float | None) -> str:
    if temp_c is None:
        return "#6c757d"
    if temp_c >= 90:
        return "#d7263d"
    if temp_c >= 80:
        return "#ff7f11"
    if temp_c >= 65:
        return "#ffb703"
    return "#2a9d8f"


def temp_line(label: str, value: float | None, color: str | None = None) -> None:
    if value is None:
        print(f"{label}: --")
        return

    suffix = f" | color={color}" if color else ""
    print(f"{label}: {value:.1f} °C{suffix}")


def submenu_line(label: str, value: float, color: str | None = None) -> None:
    suffix = f" | color={color}" if color else ""
    print(f"--{label}: {value:.1f} °C{suffix}")


def main() -> None:
    command = helper_path()
    if not command:
        print("CPU --°")
        print("---")
        print("Temperature helper not installed.")
        print(f"Install iSMC Helper | bash='{INSTALL_SCRIPT}' terminal=true refresh=true")
        print("Or install via Homebrew:")
        print("brew tap dkorunic/tap && brew install ismc | font=Menlo size=11 trim=false ansi=false")
        print("---")
        print("Refresh Now | refresh=true")
        return

    sensors, error = load_temperatures(command)
    if error:
        print("CPU --°")
        print("---")
        print(f"Temperature read failed: {error}")
        print(f"Install or Update iSMC Helper | bash='{INSTALL_SCRIPT}' terminal=true refresh=true")
        print("---")
        print("Refresh Now | refresh=true")
        return

    cpu_eff = [sensor["value"] for sensor in sensors if str(sensor["name"]).startswith("CPU Efficiency Core")]
    cpu_perf = [sensor["value"] for sensor in sensors if str(sensor["name"]).startswith("CPU Performance Core")]
    cpu_all = cpu_eff + cpu_perf
    gpu_all = [
        sensor["value"]
        for sensor in sensors
        if str(sensor["name"]).startswith("GPU ") and "Heatsink" not in str(sensor["name"])
    ]
    battery_all = [
        sensor["value"]
        for sensor in sensors
        if str(sensor["name"]).startswith("Battery ") or str(sensor["name"]) == "gas gauge battery"
    ]

    cpu_avg = average(cpu_all)
    cpu_peak = maximum(cpu_all)
    cpu_eff_avg = average(cpu_eff)
    cpu_perf_avg = average(cpu_perf)
    gpu_avg = average(gpu_all)
    gpu_peak = maximum(gpu_all)
    battery_avg = average(battery_all)
    hottest = max(sensors, key=lambda sensor: float(sensor["value"]))
    hottest_color = color_for(float(hottest["value"]))
    header_color = color_for(cpu_peak if cpu_peak is not None else float(hottest["value"]))

    if cpu_avg is not None:
        print(f"CPU {cpu_avg:.0f}C | color={header_color} sfimage=thermometer.medium")
    else:
        print(f"TMP {float(hottest['value']):.0f}C | color={hottest_color} sfimage=thermometer.medium")

    print("---")
    temp_line("CPU Average", cpu_avg, color_for(cpu_avg))
    temp_line("CPU Peak", cpu_peak, color_for(cpu_peak))
    temp_line("Efficiency Average", cpu_eff_avg)
    temp_line("Performance Average", cpu_perf_avg)
    temp_line("GPU Average", gpu_avg, color_for(gpu_avg))
    temp_line("GPU Peak", gpu_peak, color_for(gpu_peak))
    temp_line("Battery Average", battery_avg)
    print(
        f"Hottest Sensor: {hottest['name']} ({float(hottest['value']):.1f} °C)"
        f" | color={hottest_color}"
    )
    print("---")
    print("Hottest Sensors")
    for sensor in sorted(sensors, key=lambda entry: float(entry["value"]), reverse=True)[:8]:
        submenu_line(str(sensor["name"]), float(sensor["value"]), color_for(float(sensor["value"])))
    print("---")
    version = helper_version(command)
    if version:
        print(f"Helper: {version}")
    print(f"Install or Update iSMC Helper | bash='{INSTALL_SCRIPT}' terminal=true refresh=true")
    print("Open Activity Monitor | bash='open' param1='-a' param2='Activity Monitor' terminal=false")
    print("Refresh Now | refresh=true")


if __name__ == "__main__":
    main()
