#!/usr/bin/env python3

from __future__ import annotations

import argparse
import fcntl
import json
import math
import os
import shutil
import subprocess
import sys
import termios
from dataclasses import asdict, dataclass
from enum import Enum, auto
from pathlib import Path


CACHE_FILE = Path("~/.cache/kitty_grid_solver.json").expanduser()

MIN_FONT = 4.0
MAX_FONT = 50.0


# ============================================================================
# Configuration
# ============================================================================


class MatchStrategy(Enum):
    EXACT_WIDTH = auto()
    EXACT_HEIGHT = auto()
    FIT_MIN = auto()
    FIT_MAX = auto()


class SizePolicy(Enum):
    CLOSEST = auto()
    AT_LEAST = auto()
    AT_MOST = auto()


# ============================================================================
# Data
# ============================================================================


@dataclass(frozen=True)
class Allocation:
    width: int
    height: int


@dataclass(frozen=True)
class Metrics:
    font: float
    cell_width: int
    cell_height: int
    columns: int
    rows: int


@dataclass
class Probe:
    font: float
    cell_width: int
    cell_height: int


# ============================================================================
# Allocation detection
# ============================================================================


def get_allocated_size() -> Allocation | None:
    """
    Get the compositor-allocated size of the Kitty window.

    This is deliberately different from Kitty's current terminal grid.
    """

    # ------------------------------------------------------------------
    # Hyprland
    # ------------------------------------------------------------------

    if shutil.which("hyprctl"):
        try:
            result = subprocess.run(
                [
                    "hyprctl",
                    "-j",
                    "activewindow",
                ],
                capture_output=True,
                text=True,
                check=True,
            )

            data = json.loads(result.stdout)
            size = data.get("size")

            if size and len(size) == 2:
                width = int(size[0])
                height = int(size[1])

                if width > 0 and height > 0:
                    print(f"Allocation: Hyprland {width}x{height}")

                    return Allocation(
                        width,
                        height,
                    )

        except Exception:
            pass

    # ------------------------------------------------------------------
    # Sway / i3
    # ------------------------------------------------------------------

    for command in ("swaymsg", "i3-msg"):
        if not shutil.which(command):
            continue

        try:
            result = subprocess.run(
                [
                    command,
                    "-t",
                    "get_tree",
                ],
                capture_output=True,
                text=True,
                check=True,
            )

            tree = json.loads(result.stdout)

            def find_focused(node):

                if node.get("focused") and "rect" in node:
                    return node["rect"]

                for child in node.get("nodes", []) + node.get("floating_nodes", []):
                    found = find_focused(child)

                    if found:
                        return found

                return None

            rect = find_focused(tree)

            if rect:
                width = int(rect.get("width", 0))

                height = int(rect.get("height", 0))

                if width > 0 and height > 0:
                    print(f"Allocation: {command} {width}x{height}")

                    return Allocation(
                        width,
                        height,
                    )

        except Exception:
            pass

    # ------------------------------------------------------------------
    # X11
    # ------------------------------------------------------------------

    if (
        os.environ.get("DISPLAY")
        and shutil.which("xdotool")
        and shutil.which("xwininfo")
    ):
        try:
            window_id = subprocess.run(
                [
                    "xdotool",
                    "getactivewindow",
                ],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()

            if not window_id:
                raise RuntimeError("Could not determine active X11 window")

            result = subprocess.run(
                [
                    "xwininfo",
                    "-id",
                    window_id,
                ],
                capture_output=True,
                text=True,
                check=True,
            )

            width = 0
            height = 0

            for line in result.stdout.splitlines():
                line = line.strip()

                if line.startswith("Width:"):
                    width = int(line.split(":", 1)[1])

                elif line.startswith("Height:"):
                    height = int(line.split(":", 1)[1])

            if width > 0 and height > 0:
                print(f"Allocation: X11 {width}x{height}")

                return Allocation(
                    width,
                    height,
                )

        except Exception:
            pass

    # ------------------------------------------------------------------
    # Cage / pure Wayland fallback
    # ------------------------------------------------------------------

    if os.environ.get("WAYLAND_DISPLAY"):
        try:
            import tkinter as tk

            root = tk.Tk()
            root.withdraw()

            width = root.winfo_screenwidth()
            height = root.winfo_screenheight()

            root.destroy()

            if width > 0 and height > 0:
                print(f"Allocation: Wayland/Tk {width}x{height}")

                return Allocation(
                    width,
                    height,
                )

        except Exception:
            pass

    return None


# ============================================================================
# Terminal metrics
# ============================================================================


def get_metrics(font: float) -> Metrics:
    """
    Read the current terminal grid and pixel dimensions.

    Kitty reports:

        rows
        columns
        pixel width
        pixel height

    From these we obtain the actual integer cell dimensions.
    """

    fd = sys.stdin.fileno()

    data = fcntl.ioctl(
        fd,
        termios.TIOCGWINSZ,
        b"\0" * 8,
    )

    rows = int.from_bytes(
        data[0:2],
        "little",
    )

    columns = int.from_bytes(
        data[2:4],
        "little",
    )

    pixel_width = int.from_bytes(
        data[4:6],
        "little",
    )

    pixel_height = int.from_bytes(
        data[6:8],
        "little",
    )

    if rows <= 0 or columns <= 0:
        raise RuntimeError("Terminal returned an invalid grid size")

    if pixel_width <= 0 or pixel_height <= 0:
        raise RuntimeError("Terminal returned no pixel dimensions")

    cell_width = round(pixel_width / columns)

    cell_height = round(pixel_height / rows)

    return Metrics(
        font=font,
        cell_width=cell_width,
        cell_height=cell_height,
        columns=columns,
        rows=rows,
    )


# ============================================================================
# Kitty control
# ============================================================================


def set_font(font: float) -> None:

    font = max(
        MIN_FONT,
        min(
            MAX_FONT,
            font,
        ),
    )

    print(
        f"Setting Kitty font to {font:.2f}",
        flush=True,
    )

    subprocess.run(
        [
            "kitten",
            "@",
            "set-font-size",
            "--",
            f"{font:.2f}",
        ],
        check=True,
    )


# ============================================================================
# Cache
# ============================================================================


def load_cache() -> dict:

    try:
        with CACHE_FILE.open() as file:
            return json.load(file)

    except (
        OSError,
        json.JSONDecodeError,
    ):
        return {}


def save_cache(cache: dict) -> None:

    CACHE_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary = CACHE_FILE.with_suffix(".tmp")

    with temporary.open("w") as file:
        json.dump(
            cache,
            file,
            indent=2,
        )

    temporary.replace(CACHE_FILE)


# ============================================================================
# Rough estimate
# ============================================================================


def rough_font_estimate(
    allocation: Allocation,
    target_w: int,
    target_h: int,
    strategy: MatchStrategy,
) -> float:
    """
    Only used to choose a reasonable first probe.

    It is deliberately NOT used as the final model.
    """

    width_estimate = allocation.width / target_w / 0.60

    height_estimate = allocation.height / target_h

    if strategy is MatchStrategy.EXACT_WIDTH:
        estimate = width_estimate

    elif strategy is MatchStrategy.EXACT_HEIGHT:
        estimate = height_estimate

    elif strategy is MatchStrategy.FIT_MIN:
        estimate = max(
            width_estimate,
            height_estimate,
        )

    elif strategy is MatchStrategy.FIT_MAX:
        estimate = min(
            width_estimate,
            height_estimate,
        )

    else:
        raise ValueError(strategy)

    return max(
        MIN_FONT,
        min(
            MAX_FONT,
            estimate,
        ),
    )


# ============================================================================
# Required cell-size boundary
# ============================================================================


def required_cell_range(
    allocation: Allocation,
    target_w: int,
    target_h: int,
    strategy: MatchStrategy,
    policy: SizePolicy,
) -> tuple[int | None, int | None]:
    """
    Convert the desired grid into integer cell-size constraints.

    Example:

        allocation = 956px
        target     = 100 columns

    gives:

        AT_MOST:
            cell >= ceil(956 / 100)
                 >= 10

        AT_LEAST:
            cell <= floor(956 / 100)
                 <= 9
    """

    min_cell = None
    max_cell = None

    def add_minimum(value: int):

        nonlocal min_cell

        if min_cell is None:
            min_cell = value
        else:
            min_cell = max(
                min_cell,
                value,
            )

    def add_maximum(value: int):

        nonlocal max_cell

        if max_cell is None:
            max_cell = value
        else:
            max_cell = min(
                max_cell,
                value,
            )

    # ------------------------------------------------------------------
    # Width
    # ------------------------------------------------------------------

    if strategy in (
        MatchStrategy.EXACT_WIDTH,
        MatchStrategy.FIT_MIN,
        MatchStrategy.FIT_MAX,
    ):
        if policy is SizePolicy.AT_MOST:
            add_minimum(math.ceil(allocation.width / target_w))

        elif policy is SizePolicy.AT_LEAST:
            add_maximum(allocation.width // target_w)

    # ------------------------------------------------------------------
    # Height
    # ------------------------------------------------------------------

    if strategy in (
        MatchStrategy.EXACT_HEIGHT,
        MatchStrategy.FIT_MIN,
        MatchStrategy.FIT_MAX,
    ):
        if policy is SizePolicy.AT_MOST:
            add_minimum(math.ceil(allocation.height / target_h))

        elif policy is SizePolicy.AT_LEAST:
            add_maximum(allocation.height // target_h)

    return (
        min_cell,
        max_cell,
    )


# ============================================================================
# Probe
# ============================================================================


def probe_font(font: float) -> Probe:

    font = round(
        max(
            MIN_FONT,
            min(
                MAX_FONT,
                font,
            ),
        ),
        2,
    )

    set_font(font)

    metrics = get_metrics(font)

    print(
        f"Probe {font:.2f}: "
        f"cell={metrics.cell_width}x"
        f"{metrics.cell_height} "
        f"grid={metrics.columns}x"
        f"{metrics.rows}",
        flush=True,
    )

    return Probe(
        font=font,
        cell_width=metrics.cell_width,
        cell_height=metrics.cell_height,
    )


# ============================================================================
# Initial calibration
# ============================================================================


def initial_calibration(
    allocation: Allocation,
    target_w: int,
    target_h: int,
    strategy: MatchStrategy,
    policy: SizePolicy,
) -> list[Probe]:

    estimate = rough_font_estimate(
        allocation,
        target_w,
        target_h,
        strategy,
    )

    first_font = round(estimate)

    first_font = max(
        int(MIN_FONT),
        min(
            int(MAX_FONT),
            first_font,
        ),
    )

    first = probe_font(float(first_font))

    min_cell, max_cell = required_cell_range(
        allocation,
        target_w,
        target_h,
        strategy,
        policy,
    )

    # ------------------------------------------------------------------
    # Determine which cell boundary we actually want.
    # ------------------------------------------------------------------

    if policy is SizePolicy.AT_MOST:
        target_cell = min_cell

    elif policy is SizePolicy.AT_LEAST:
        target_cell = max_cell

    else:
        target_cell = min_cell if min_cell is not None else max_cell

    if target_cell is None:
        target_cell = first.cell_width

    # ------------------------------------------------------------------
    # Determine measured dimension.
    # ------------------------------------------------------------------

    if strategy is MatchStrategy.EXACT_HEIGHT:
        current_cell = first.cell_height

    else:
        current_cell = first.cell_width

    # ------------------------------------------------------------------
    # Roughly interpolate toward the required cell size.
    #
    # This is only for selecting the next probe.
    # ------------------------------------------------------------------

    if current_cell > 0:
        second_font = first.font * target_cell / current_cell

    else:
        second_font = first.font

    second_font = max(
        MIN_FONT,
        min(
            MAX_FONT,
            second_font,
        ),
    )

    second_font = round(
        second_font,
        2,
    )

    # Ensure we actually move away from the first probe.

    if abs(second_font - first.font) < 0.01:
        if policy is SizePolicy.AT_LEAST:
            second_font = first.font - 1.0

        elif policy is SizePolicy.AT_MOST:
            second_font = first.font + 1.0

        second_font = max(
            MIN_FONT,
            min(
                MAX_FONT,
                second_font,
            ),
        )

    second = probe_font(second_font)

    return [
        first,
        second,
    ]


# ============================================================================
# Grid helpers
# ============================================================================


def grid_for_probe(
    allocation: Allocation,
    probe: Probe,
) -> tuple[int, int]:

    return (
        allocation.width // probe.cell_width,
        allocation.height // probe.cell_height,
    )


def satisfies_policy(
    grid: tuple[int, int],
    target_w: int,
    target_h: int,
    strategy: MatchStrategy,
    policy: SizePolicy,
) -> bool:

    columns, rows = grid

    if policy is SizePolicy.CLOSEST:
        return True

    if strategy is MatchStrategy.EXACT_WIDTH:
        if policy is SizePolicy.AT_LEAST:
            return columns >= target_w

        return columns <= target_w

    if strategy is MatchStrategy.EXACT_HEIGHT:
        if policy is SizePolicy.AT_LEAST:
            return rows >= target_h

        return rows <= target_h

    if strategy is MatchStrategy.FIT_MIN:
        if policy is SizePolicy.AT_LEAST:
            return columns >= target_w or rows >= target_h

        return columns <= target_w or rows <= target_h

    # FIT_MAX

    if policy is SizePolicy.AT_LEAST:
        return columns >= target_w and rows >= target_h

    return columns <= target_w and rows <= target_h


def score_grid(
    grid: tuple[int, int],
    target_w: int,
    target_h: int,
    strategy: MatchStrategy,
) -> tuple:

    columns, rows = grid

    if strategy is MatchStrategy.EXACT_WIDTH:
        return (
            abs(columns - target_w),
            abs(rows - target_h),
        )

    if strategy is MatchStrategy.EXACT_HEIGHT:
        return (
            abs(rows - target_h),
            abs(columns - target_w),
        )

    if strategy is MatchStrategy.FIT_MIN:
        return (
            abs(min(columns, rows) - min(target_w, target_h)),
            abs(columns - target_w) + abs(rows - target_h),
        )

    return (
        abs(max(columns, rows) - max(target_w, target_h)),
        abs(columns - target_w) + abs(rows - target_h),
    )


# ============================================================================
# Targeted probe
# ============================================================================


def choose_targeted_font(
    probes: list[Probe],
    target_cell: int,
    strategy: MatchStrategy,
) -> float:
    """
    Use the closest measured state to estimate where the requested
    integer cell-size boundary lies.

    This does NOT assume a globally linear relationship between
    font size and cell size.
    """

    if strategy is MatchStrategy.EXACT_HEIGHT:
        closest = min(
            probes,
            key=lambda probe: abs(probe.cell_height - target_cell),
        )

        current_cell = closest.cell_height

    else:
        closest = min(
            probes,
            key=lambda probe: abs(probe.cell_width - target_cell),
        )

        current_cell = closest.cell_width

    if current_cell <= 0:
        return closest.font

    estimate = closest.font * target_cell / current_cell

    return max(
        MIN_FONT,
        min(
            MAX_FONT,
            round(
                estimate,
                2,
            ),
        ),
    )


# ============================================================================
# Solve
# ============================================================================


def solve_from_probes(
    allocation: Allocation,
    probes: list[Probe],
    target_w: int,
    target_h: int,
    strategy: MatchStrategy,
    policy: SizePolicy,
) -> tuple[float, tuple[int, int], Probe]:

    # ==================================================================
    # CLOSEST
    # ==================================================================

    if policy is SizePolicy.CLOSEST:
        candidates = []

        for probe in probes:
            grid = grid_for_probe(
                allocation,
                probe,
            )

            candidates.append(
                (
                    score_grid(
                        grid,
                        target_w,
                        target_h,
                        strategy,
                    ),
                    probe,
                    grid,
                )
            )

        candidates.sort(key=lambda item: item[0])

        _, probe, grid = candidates[0]

        return (
            probe.font,
            grid,
            probe,
        )

    # ==================================================================
    # AT_LEAST / AT_MOST
    #
    # IMPORTANT:
    #
    # We do NOT stop merely because a probe satisfies the policy.
    #
    # We need the closest grid to the requested boundary.
    # ==================================================================

    min_cell, max_cell = required_cell_range(
        allocation,
        target_w,
        target_h,
        strategy,
        policy,
    )

    if policy is SizePolicy.AT_MOST:
        target_cell = min_cell

    else:
        target_cell = max_cell

    if target_cell is None:
        raise RuntimeError("Could not determine target cell boundary")

    # ------------------------------------------------------------------
    # First, see whether we already measured the exact desired cell
    # size.
    # ------------------------------------------------------------------

    exact = []

    for probe in probes:
        cell = (
            probe.cell_height
            if strategy is MatchStrategy.EXACT_HEIGHT
            else probe.cell_width
        )

        if cell == target_cell:
            grid = grid_for_probe(
                allocation,
                probe,
            )

            if satisfies_policy(
                grid,
                target_w,
                target_h,
                strategy,
                policy,
            ):
                exact.append(
                    (
                        score_grid(
                            grid,
                            target_w,
                            target_h,
                            strategy,
                        ),
                        probe,
                        grid,
                    )
                )

    if exact:
        exact.sort(key=lambda item: item[0])

        _, probe, grid = exact[0]

        return (
            probe.font,
            grid,
            probe,
        )

    # ------------------------------------------------------------------
    # We have not measured the required cell size.
    #
    # Always probe toward it, even if an existing probe already
    # satisfies the policy.
    # ------------------------------------------------------------------

    target_font = choose_targeted_font(
        probes,
        target_cell,
        strategy,
    )

    # ------------------------------------------------------------------
    # If interpolation landed on an existing probe, move toward the
    # target using the smallest useful font displacement.
    # ------------------------------------------------------------------

    if any(abs(probe.font - target_font) < 0.01 for probe in probes):
        if policy is SizePolicy.AT_MOST:
            target_font = min(
                (probe.font for probe in probes if probe.font > target_font),
                default=target_font + 0.5,
            )

        else:
            target_font = max(
                (probe.font for probe in probes if probe.font < target_font),
                default=target_font - 0.5,
            )

        target_font = max(
            MIN_FONT,
            min(
                MAX_FONT,
                target_font,
            ),
        )

    print()
    print(f"Targeted probe: font={target_font:.2f}, target cell={target_cell}")

    new_probe = probe_font(target_font)

    probes.append(new_probe)

    # ==================================================================
    # Check whether we got the desired cell size.
    # ==================================================================

    matching = []

    for probe in probes:
        cell = (
            probe.cell_height
            if strategy is MatchStrategy.EXACT_HEIGHT
            else probe.cell_width
        )

        if cell != target_cell:
            continue

        grid = grid_for_probe(
            allocation,
            probe,
        )

        if satisfies_policy(
            grid,
            target_w,
            target_h,
            strategy,
            policy,
        ):
            matching.append(
                (
                    score_grid(
                        grid,
                        target_w,
                        target_h,
                        strategy,
                    ),
                    probe,
                    grid,
                )
            )

    if matching:
        matching.sort(key=lambda item: item[0])

        _, probe, grid = matching[0]

        return (
            probe.font,
            grid,
            probe,
        )

    # ==================================================================
    # The interpolation missed the boundary.
    #
    # This can happen because font->cell is discrete.
    #
    # We therefore choose the best VALID measured state, but make the
    # failure explicit. In normal cases the targeted probe should hit
    # the requested cell size.
    # ==================================================================

    valid = []

    for probe in probes:
        grid = grid_for_probe(
            allocation,
            probe,
        )

        if satisfies_policy(
            grid,
            target_w,
            target_h,
            strategy,
            policy,
        ):
            valid.append(
                (
                    abs(
                        (
                            probe.cell_height
                            if strategy is MatchStrategy.EXACT_HEIGHT
                            else probe.cell_width
                        )
                        - target_cell
                    ),
                    score_grid(
                        grid,
                        target_w,
                        target_h,
                        strategy,
                    ),
                    probe,
                    grid,
                )
            )

    if valid:
        valid.sort(
            key=lambda item: (
                item[0],
                item[1],
            )
        )

        _, _, probe, grid = valid[0]

        print()
        print("WARNING: targeted probe did not hit the exact cell boundary.")

        return (
            probe.font,
            grid,
            probe,
        )

    raise RuntimeError("No measured font satisfies the requested policy")


# ============================================================================
# Main solver
# ============================================================================


def solve(
    target_w: int,
    target_h: int,
    strategy: MatchStrategy,
    policy: SizePolicy,
) -> None:

    allocation = get_allocated_size()

    if allocation is None:
        raise RuntimeError("Could not determine allocated window size")

    cache = load_cache()

    allocation_key = f"{allocation.width}x{allocation.height}"

    solution_key = f"{target_w}x{target_h}:{strategy.name}:{policy.name}"

    allocation_cache = cache.get(
        allocation_key,
        {},
    )

    cached_solution = allocation_cache.get("solutions", {}).get(solution_key)

    # ==================================================================
    # CACHE HIT
    # ==================================================================

    if cached_solution:
        print()
        print("CACHE HIT")
        print("---------")

        font = float(cached_solution["font"])

        print(f"Cached font: {font:.2f}")

        set_font(font)

        actual = get_metrics(font)

        print(f"Actual cell: {actual.cell_width}x{actual.cell_height}")

        print(f"Actual grid: {actual.columns}x{actual.rows}")

        return

    # ==================================================================
    # CACHE MISS
    # ==================================================================

    print()
    print("CACHE MISS")
    print("----------")

    probes = initial_calibration(
        allocation,
        target_w,
        target_h,
        strategy,
        policy,
    )

    print()
    print("OBSERVED STATES")
    print("----------------")

    for probe in probes:
        grid = grid_for_probe(
            allocation,
            probe,
        )

        print(
            f"{probe.font:.2f}: "
            f"cell={probe.cell_width}x"
            f"{probe.cell_height} "
            f"grid={grid[0]}x"
            f"{grid[1]}"
        )

    # ==================================================================
    # SOLVE
    # ==================================================================

    print()
    print("SOLVING")
    print("-------")

    font, predicted_grid, chosen = solve_from_probes(
        allocation,
        probes,
        target_w,
        target_h,
        strategy,
        policy,
    )

    print()
    print("RESULT")
    print("------")

    print(f"Chosen font : {font:.2f}")

    print(f"Predicted   : {predicted_grid[0]}x{predicted_grid[1]}")

    print(f"Cell        : {chosen.cell_width}x{chosen.cell_height}")

    # ==================================================================
    # FINAL
    # ==================================================================

    print()
    print("FINAL")
    print("-----")

    set_font(font)

    actual = get_metrics(font)

    print(f"Actual cell : {actual.cell_width}x{actual.cell_height}")

    print(f"Actual grid : {actual.columns}x{actual.rows}")

    if not satisfies_policy(
        (
            actual.columns,
            actual.rows,
        ),
        target_w,
        target_h,
        strategy,
        policy,
    ):
        print()
        print("WARNING: final Kitty grid does not satisfy the requested policy.")

    # ==================================================================
    # CACHE
    # ==================================================================

    allocation_cache.setdefault(
        "solutions",
        {},
    )

    allocation_cache["solutions"][solution_key] = {
        "font": font,
        "cell_width": (chosen.cell_width),
        "cell_height": (chosen.cell_height),
        "predicted_grid": [
            predicted_grid[0],
            predicted_grid[1],
        ],
        "actual_grid": [
            actual.columns,
            actual.rows,
        ],
        "probes": [asdict(probe) for probe in probes],
    }

    cache[allocation_key] = allocation_cache

    save_cache(cache)

    print()
    print(f"Saved cache: {CACHE_FILE}")


# ============================================================================
# CLI
# ============================================================================


def main() -> None:

    parser = argparse.ArgumentParser(
        description=("Find a Kitty font size that produces a requested terminal grid.")
    )

    parser.add_argument(
        "width",
        type=int,
    )

    parser.add_argument(
        "height",
        type=int,
    )

    parser.add_argument(
        "--strategy",
        choices=[strategy.name for strategy in MatchStrategy],
        default="EXACT_WIDTH",
    )

    parser.add_argument(
        "--policy",
        choices=[policy.name for policy in SizePolicy],
        default="CLOSEST",
    )

    args = parser.parse_args()

    solve(
        target_w=args.width,
        target_h=args.height,
        strategy=MatchStrategy[args.strategy],
        policy=SizePolicy[args.policy],
    )


if __name__ == "__main__":
    main()
