#!/usr/bin/env python3
"""Order screens using xrandr."""
import argparse
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


def read_monitor_config():
    """Read configuration of monitors from file"""
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
                or line.startswith("DVI-")
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


def get_x_resolution(monitor):
    """Get the x resolution from a string like 1920x1200"""
    resolution_string = monitor["resolution"]
    parts = resolution_string.split("x")
    if "rotate" in monitor and monitor["rotate"] in ["left", "right"]:
        return int(parts[1])
    return int(parts[0])


def get_y_resolution(monitor):
    """Get the x resolution from a string like 1920x1200"""
    resolution_string = monitor["resolution"]
    parts = resolution_string.split("x")
    if "rotate" in monitor and monitor["rotate"] in ["left", "right"]:
        return int(parts[0])
    return int(parts[1])


def configure_monitors(monitors, config):
    """Return monitors configured by config"""
    selected_monitors = {}
    for identifier, monitor in monitors.items():
        monitor_config = config.get(monitor["edid"], None)
        if monitor_config is None:
            print(f"Did not find monitor {identifier} in {get_config_file_name()}")
            print("Insert:")
            print(
                json.dumps(
                    {
                        monitor["edid"]: {
                            "order": "<Order goes here. E. g. 1, 2, 3>",
                            "Description": "<Short description of monitor>",
                            "resolution": "Optional: Override default resolution. Format WxH",
                            "rotate": "Optional, valid are 'left', 'right'",
                        }
                    },
                    indent=4,
                )
            )
        else:
            monitor.update(monitor_config)
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


def generate_xrandr_command(ordered_monitors, disabled, force_panning):
    """Generate command

    Example resulting command
    xrandr --fb 5760x1200 \
        --output DP-6 --mode 1920x1080 --panning 1920x1080+0+0 --pos 0x0 \
        --output DP-0.2.1.8 --mode 1920x1200 --panning 1920x1200+1920+0 --pos 1920x0 \
        --output DP-0.2.1.1 --mode 1920x1200 --panning 1920x1200+3840+0 --pos 3840x0
    """
    offsets = [0]
    offsets.extend(
        accumulate(get_x_resolution(monitor) for monitor in ordered_monitors.values())
    )
    monitor_info = [
        (identifier, monitor["resolution"], offset, monitor.get("rotate", None))
        for (identifier, monitor), offset in zip(ordered_monitors.items(), offsets)
    ]
    fb_width = sum(get_x_resolution(monitor) for monitor in ordered_monitors.values())
    fb_height = max(get_y_resolution(monitor) for monitor in ordered_monitors.values())
    res = ["xrandr", "--fb", f"{fb_width}x{fb_height}"]
    for identifier, resolution, monitor_x_pos, rotate in monitor_info:
        res.extend(
            [
                "--output",
                identifier,
                "--mode",
                resolution,
                "--pos",
                f"{monitor_x_pos}x0",
            ]
        )
        if force_panning:
            res.extend(
                [
                    "--panning",
                    f"{resolution}+{monitor_x_pos}+0",
                ]
            )
        if rotate:
            res.extend(
                [
                    "--rotate",
                    rotate,
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


def is_i3_running():
    """Check if i3 is running"""
    return subprocess.run(["pgrep", "-x", "i3"], check=False, capture_output=True)


def generate_i3_commands(ordered_monitors):
    """Generate commands to order workspaces in i3"""
    if not is_i3_running():
        return []
    return [
        [
            "i3-msg",
            f"workspace number {monitor['order']}; move workspace to output {output}",
        ]
        for output, monitor in ordered_monitors.items()
    ]


def main():
    """Reorder monitors using xrandr"""
    parser = argparse.ArgumentParser("Screenorder")
    parser.add_argument("--dry_run", action="store_true")
    parser.add_argument("--force_panning", action="store_true")
    args = parser.parse_args()
    monitors, disabled = get_monitors_info()
    config = read_monitor_config()
    ordered_monitors = configure_monitors(monitors, config)
    if not ordered_monitors:
        sys.exit(1)
    cmd = generate_xrandr_command(ordered_monitors, disabled, args.force_panning)
    if not cmd:
        sys.exit(1)
    print(f"Running \"{' '.join(cmd)}\"")
    if not args.dry_run:
        subprocess.run(cmd, check=True)
    cmds = generate_i3_commands(ordered_monitors)
    for cmd in cmds:
        print(f"Running \"{' '.join(cmd)}\"")
        if not args.dry_run:
            subprocess.run(cmd, check=True, capture_output=True)
    sys.exit(0)


if __name__ == "__main__":
    main()
