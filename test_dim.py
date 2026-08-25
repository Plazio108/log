import os
import json
import subprocess
from enum import Enum, auto
from pathlib import Path


class MatchStrategy(Enum):
    EXACT_WIDTH = auto()
    EXACT_HEIGHT = auto()
    FIT_MIN = auto()
    FIT_MAX = auto()


class SizePolicy(Enum):
    CLOSEST = auto()
    AT_LEAST = auto()  # Grid must be >= target (no clipping)
    AT_MOST = auto()  # Grid must be <= target (fits within bounds)


class SearchMethod(Enum):
    STEP_WALK = auto()  # Fast baby steps in the correct direction
    BINARY_SEARCH = auto()  # Tight bounded binary search around interpolation baseline


class KittyGridProber:
    def __init__(self, cache_file="~/.cache/kitty_font_probe.json"):
        self.cache_file = Path(cache_file).expanduser()
        self.cache = self._load_cache()

    def _load_cache(self):
        if self.cache_file.exists():
            try:
                with open(self.cache_file, "r") as f:
                    return json.load(f)
            except json.JSONDecodeError:
                pass
        return {}

    def _save_cache(self):
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.cache_file, "w") as f:
            json.dump(self.cache, f, indent=4)

    def clear_cache(self):
        self.cache = {}
        if self.cache_file.exists():
            self.cache_file.unlink()
        print("Kitty font probe cache cleared successfully.")

    def _get_grid(self):
        size = os.get_terminal_size()
        return size.columns, size.lines

    def _get_quantized_window_size(self):
        """
        Fetches window pixel size and quantizes it to the nearest 40 pixels.
        This absorbs tiny cell-snapping pixel shifts from font-size shortcuts
        while catching real window resizes (windowed vs fullscreen).
        """
        w, h = 0, 0
        try:
            res = subprocess.run(
                ["kitten", "+kitten", "icat", "--print-window-size"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            if "x" in res:
                parts = res.split("x")
                w, h = int(parts[0]), int(parts[1])
        except Exception:
            pass

        if w == 0 or h == 0:
            size = os.get_terminal_size()
            w, h = size.columns * 10, size.lines * 20

        # Bucket to nearest 40px
        return round(w / 40) * 40, round(h / 40) * 40

    def _set_font(self, size):
        safe_size = max(4.0, min(50.0, size))
        subprocess.run(
            ["kitten", "@", "set-font-size", "--", f"{safe_size:.2f}"],
            capture_output=True,
            check=True,
        )

    def probe(
        self,
        target_w,
        target_h,
        strategy=MatchStrategy.EXACT_WIDTH,
        policy=SizePolicy.CLOSEST,
        method=SearchMethod.STEP_WALK,
    ):

        # Build cache key using quantized window geometry
        win_w, win_h = self._get_quantized_window_size()
        cache_key = f"win_{win_w}x{win_h}_w{target_w}_h{target_h}_{strategy.name}_{policy.name}_{method.name}"

        if cache_key in self.cache:
            font_size = self.cache[cache_key]
            self._set_font(font_size)
            print(
                f"Cache hit! Applied cached font size: {font_size} (Window bucket: {win_w}x{win_h})"
            )
            return font_size

        print(
            f"Cache miss for window bucket {win_w}x{win_h}. Probing optimal font size..."
        )

        # --- Phase 1: Fast Interpolation Baseline ---
        current_font = 12.0
        for _ in range(2):
            self._set_font(current_font)
            cols, lines = self._get_grid()
            val = (
                cols
                if strategy in (MatchStrategy.EXACT_WIDTH, MatchStrategy.FIT_MIN)
                else lines
            )
            target = (
                target_w
                if strategy in (MatchStrategy.EXACT_WIDTH, MatchStrategy.FIT_MIN)
                else target_h
            )
            if target == 0 or val == 0:
                break
            current_font = current_font * (val / target)
            current_font = max(4.0, min(50.0, current_font))

        current_font = round(current_font, 1)
        self._set_font(current_font)
        best_font = current_font
        cols, lines = self._get_grid()

        val = (
            cols
            if strategy in (MatchStrategy.EXACT_WIDTH, MatchStrategy.FIT_MIN)
            else lines
        )
        target = (
            target_w
            if strategy in (MatchStrategy.EXACT_WIDTH, MatchStrategy.FIT_MIN)
            else target_h
        )

        # --- Phase 2: Policy Enforcement ---
        if method == SearchMethod.STEP_WALK:
            step = 0.2
            for _ in range(15):
                condition_met = False
                if policy == SizePolicy.CLOSEST:
                    condition_met = True
                elif policy == SizePolicy.AT_LEAST:
                    condition_met = val >= target
                elif policy == SizePolicy.AT_MOST:
                    condition_met = val <= target

                if condition_met and policy != SizePolicy.CLOSEST:
                    break

                if val < target:
                    current_font -= step
                else:
                    current_font += step

                self._set_font(current_font)
                cols, lines = self._get_grid()
                new_val = (
                    cols
                    if strategy in (MatchStrategy.EXACT_WIDTH, MatchStrategy.FIT_MIN)
                    else lines
                )

                if new_val == val:
                    step += 0.2  # Dynamic escalation if grid hasn't shifted yet
                else:
                    step = 0.2
                    val = new_val
                    best_font = current_font

        elif method == SearchMethod.BINARY_SEARCH:
            low = max(4.0, current_font - 1.5)
            high = min(50.0, current_font + 1.5)
            best_diff = float("inf")

            for _ in range(6):
                mid = (low + high) / 2.0
                self._set_font(mid)
                cols, lines = self._get_grid()
                val = (
                    cols
                    if strategy in (MatchStrategy.EXACT_WIDTH, MatchStrategy.FIT_MIN)
                    else lines
                )

                diff = abs(val - target)
                if policy == SizePolicy.CLOSEST:
                    if diff < best_diff:
                        best_diff = diff
                        best_font = mid
                elif policy == SizePolicy.AT_LEAST:
                    if val >= target and diff < best_diff:
                        best_diff = diff
                        best_font = mid
                elif policy == SizePolicy.AT_MOST:
                    if val <= target and diff < best_diff:
                        best_diff = diff
                        best_font = mid

                if val > target:
                    low = mid
                else:
                    high = mid

        # Final application & caching
        final_font = round(best_font, 1)
        self._set_font(final_font)
        self.cache[cache_key] = final_font
        self._save_cache()

        final_cols, final_lines = self._get_grid()
        print(f"Probe complete! Font: {final_font} -> Grid: {final_cols}x{final_lines}")
        return final_font


if __name__ == "__main__":
    prober = KittyGridProber()

    # prober.clear_cache()
    # Test execution
    prober.probe(
        target_w=100,
        target_h=30,
        strategy=MatchStrategy.EXACT_WIDTH,
        policy=SizePolicy.AT_MOST,
        method=SearchMethod.STEP_WALK,
    )
