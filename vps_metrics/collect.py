"""Read Linux host counters without a Docker socket or IP networking."""

import datetime as dt
import os
from pathlib import Path
import time


def cpu_ticks(text):
    fields = [int(value) for value in text.splitlines()[0].split()[1:9]]
    if len(fields) != 8:
        raise ValueError("Incomplete aggregate CPU counters")
    return sum(fields), fields[3] + fields[4]


def cpu_percent(before, after):
    total, idle = after[0] - before[0], after[1] - before[1]
    if total <= 0 or idle < 0 or idle > total:
        raise ValueError("Invalid CPU sampling interval")
    return (total - idle) / total * 100


def memory_values(text):
    values = {}
    for line in text.splitlines():
        key, value = line.split(":", 1)
        values[key] = int(value.split()[0]) * 1024
    return {"ram_total_bytes": values["MemTotal"], "ram_available_bytes": values["MemAvailable"],
            "ram_used_bytes": values["MemTotal"] - values["MemAvailable"],
            "swap_total_bytes": values["SwapTotal"], "swap_used_bytes": values["SwapTotal"] - values["SwapFree"]}


def network_counters(text):
    interfaces = {}
    for line in text.splitlines()[2:]:
        name, values = line.split(":", 1)
        name, values = name.strip(), values.split()
        if name != "lo":
            interfaces[name] = {"rx_bytes": int(values[0]), "tx_bytes": int(values[8])}
    return interfaces


def network_rates(current, previous, interval):
    result = {}
    for name, counters in current.items():
        values = dict(counters)
        for direction in ("rx", "tx"):
            key = direction + "_bytes"
            before = previous.get(name, {}).get(key)
            values[key + "_per_second"] = ((counters[key] - before) / interval
                if before is not None and interval is not None and interval > 0 and counters[key] >= before else None)
        result[name] = values
    return result


def snapshot(disk_path, previous=None, proc=Path("/proc")):
    def counters():
        return {"boot_id": (proc / "sys/kernel/random/boot_id").read_text().strip(),
                "monotonic_ns": time.monotonic_ns(),
                "cpu": list(cpu_ticks((proc / "stat").read_text())),
                "network": network_counters((proc / "net/dev").read_text())}

    current = counters()
    interval = None
    if previous and previous["boot_id"] == current["boot_id"]:
        delta = (current["monotonic_ns"] - previous["monotonic_ns"]) / 1e9
        if 0 < delta <= 120:
            interval = delta
    if interval is None:
        before = current
        time.sleep(1)
        current = counters()
        cpu_interval = (current["monotonic_ns"] - before["monotonic_ns"]) / 1e9
    else:
        before, cpu_interval = previous, interval
    disk = os.statvfs(disk_path)
    load = os.getloadavg()
    sample = {"schema_version": 1, "scope": "host",
              "captured_at": dt.datetime.now(dt.timezone.utc).isoformat(),
              "cpu_percent": cpu_percent(before["cpu"], current["cpu"]), "cpu_window_seconds": cpu_interval,
              **memory_values((proc / "meminfo").read_text()),
              "disk_total_bytes": disk.f_blocks * disk.f_frsize,
              "disk_used_bytes": (disk.f_blocks - disk.f_bfree) * disk.f_frsize,
              "disk_free_bytes": disk.f_bfree * disk.f_frsize,
              "disk_available_bytes": disk.f_bavail * disk.f_frsize,
              "load_1m": load[0], "load_5m": load[1], "load_15m": load[2],
              "uptime_seconds": float((proc / "uptime").read_text().split()[0]),
              "network": network_rates(current["network"], previous["network"] if interval is not None else {}, interval)}
    return sample, current
