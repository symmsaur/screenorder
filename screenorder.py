#!/usr/bin/env python3
"""Order screens using xrandr."""
import json
import os
import re
import subprocess
import sys

from itertools import accumulate
from pathlib import Path
from pprint import pprint


def get_config_file_name():
    """Get the config file path."""
    return os.path.join(str(Path.home()), ".config/screenorder/screenorder_config.json")


def read_order_info():
    """Read info about monitors from file"""
    config_path = Path(get_config_file_name())
    if not config_path.is_file():
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, "w", encoding="utf8") as config_file:
            config_file.write("{}")
    with open(
        config_path,
        "r",
        encoding="utf8",
    ) as screen_order_file:
        return json.load(screen_order_file)


def get_monitors_info():
    """Get information about monitors from xrandr"""
    xrandr_output = subprocess.run(
        [
            "xrandr",
            "--verbose",
        ],
        capture_output=True,
        encoding="utf8",
        check=True,
    ).stdout
    state = "scanning"
    identifier = None
    res = {}
    disabled = set()
    tmp_res = []
    for line in xrandr_output.splitlines():
        if state == "scanning":
            if line.strip() == "EDID:":
                state = "munching"
            elif (
                line.startswith("DP-")
                or line.startswith("HDMI-")
                or line.startswith("eDP-")
            ):
                if identifier is not None and identifier not in res:
                    disabled.add(identifier)
                identifier = line.split()[0]
            elif match := re.match(r"\s*(\d+x\d+).*\+preferred", line):
                res[identifier]["resolution"] = match.groups()[0]
        elif state == "munching":
            if ":" in line:
                state = "scanning"
                res[identifier] = {"edid": "".join(tmp_res)}
                tmp_res = []
            else:
                tmp_res.append(line.strip())
    return res, disabled


def get_x_resolution(resolution_string):
    """Get the x resolution from a string like 1920x1200"""
    parts = resolution_string.split("x")
    return int(parts[0])


def get_y_resolution(resolution_string):
    """Get the x resolution from a string like 1920x1200"""
    parts = resolution_string.split("x")
    return int(parts[1])


def order_monitors(monitors, order_info):
    """Return monitors ordered by order_info"""
    selected_monitors = {}
    for identifier, monitor in monitors.items():
        monitor_order_info = order_info.get(monitor["edid"], None)
        if monitor_order_info is None:
            print(f"Did not find monitor {identifier} in {get_config_file_name()}")
            print("Insert:")
            print(
                json.dumps(
                    {
                        monitor["edid"]: {
                            "order": "<Order goes here. E. g. 1, 2, 3>",
                            "Description": "<Short description of monitor>",
                        }
                    },
                    indent=4,
                )
            )
        else:
            monitor["order"] = monitor_order_info["order"]
            selected_monitors[identifier] = monitor

    if len(selected_monitors) != len(
        set(monitor["order"] for monitor in selected_monitors.values())
    ):
        print("Monitor order collision in set:")
        pprint(selected_monitors)
        return None
    ordered_monitors = dict(
        sorted(selected_monitors.items(), key=lambda item: item[1]["order"])
    )
    return ordered_monitors


def generate_xrandr_command(ordered_monitors, disabled):
    """Generate command

    Example resulting command
    xrandr --fb 5760x1200 \
        --output DP-6 --mode 1920x1080 --panning 1920x1080+0+0 --pos 0x0 \
        --output DP-0.2.1.8 --mode 1920x1200 --panning 1920x1200+1920+0 --pos 1920x0 \
        --output DP-0.2.1.1 --mode 1920x1200 --panning 1920x1200+3840+0 --pos 3840x0
    """
    offsets = [0]
    offsets.extend(
        accumulate(
            get_x_resolution(monitor["resolution"])
            for monitor in ordered_monitors.values()
        )
    )
    monitor_info = [
        (identifier, monitor["resolution"], offset)
        for (identifier, monitor), offset in zip(ordered_monitors.items(), offsets)
    ]
    fb_width = sum(
        get_x_resolution(monitor["resolution"]) for monitor in ordered_monitors.values()
    )
    fb_height = max(
        get_y_resolution(monitor["resolution"]) for monitor in ordered_monitors.values()
    )
    res = ["xrandr", "--fb", f"{fb_width}x{fb_height}"]
    for identifier, resolution, monitor_x_pos in monitor_info:
        res.extend(
            [
                "--output",
                identifier,
                "--mode",
                resolution,
                "--panning",
                f"{resolution}+{monitor_x_pos}+0",
                "--pos",
                f"{monitor_x_pos}x0",
            ]
        )
    for identifier in disabled:
        res.extend(
            [
                "--output",
                identifier,
                "--off",
            ]
        )
    return res


def main():
    """Reorder monitors using xrandr"""
    monitors, disabled = get_monitors_info()
    order_info = read_order_info()
    ordered_monitors = order_monitors(monitors, order_info)
    if not order_monitors:
        sys.exit(1)
    cmd = generate_xrandr_command(ordered_monitors, disabled)
    if not cmd:
        sys.exit(1)
    print(f"Running \"{' '.join(cmd)}\"")
    # subprocess.run(cmd, check=True)
    sys.exit(0)


if __name__ == "__main__":
    main()
