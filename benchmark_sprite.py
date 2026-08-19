import argparse
import mmap
import os
import struct
import time

from gleaf import TerminalCanvas


# --- Mock Canvas for Standalone Benchmarking ---
class MockCanvas:
    def __init__(self, width: int, height: int):
        self.width = width
        self.height = height
        # Pre-fill canvas cell state
        self._grid = {
            (x, y): (" ", (0, 0, 0), (0, 0, 0), 0)
            for y in range(height)
            for x in range(width)
        }

    def get_cell(self, x: int, y: int):
        return self._grid.get((x, y)) or (" ", (0, 0, 0), (0, 0, 0), 0)

    def put_str(self, x: int, y: int, char, fg, bg, style):
        pass  # Fast no-op to isolate engine drawing loop overhead


# --- Base Class Stub (if not importing from your engine) ---
class BaseWidget:
    def __init__(self, name: str, x, y, z_index: int):
        self.name = name
        self.x = x
        self.y = y
        self.z_index = z_index

    def get_coords(self, canvas, w, h, config):
        return 0, 0


# --- Parent Class ---
class TransparentSpriteWidget(BaseWidget):
    """Renders a custom matrix format with true transparency support."""

    def __init__(self, name: str, x, y, z_index: int, matrix: list):
        super().__init__(name, x, y, z_index)
        self.matrix = matrix

    def draw(self, canvas: MockCanvas, config: dict):
        w = len(self.matrix[0]) if self.matrix else 0
        h = len(self.matrix)
        start_x, start_y = self.get_coords(canvas, w, h, config)

        for dy, row in enumerate(self.matrix):
            for dx, cell in enumerate(row):
                if not cell:
                    continue

                c_x = start_x + dx
                c_y = start_y + dy

                old_char, old_fg, old_bg, old_style = canvas.get_cell(c_x, c_y)

                new_char = cell.get("char")
                new_char = new_char if new_char is not None else old_char

                new_fg = cell.get("fg")
                new_fg = tuple(new_fg) if new_fg else old_fg

                new_bg = cell.get("bg")
                new_bg = tuple(new_bg) if new_bg else old_bg

                new_style = cell.get("style")
                new_style = new_style if new_style is not None else old_style

                canvas.put_str(c_x, c_y, new_char, new_fg, new_bg, new_style)


# --- In-Memory Mmap Benchmark Target ---
class BenchmarkSpriteWidget(TransparentSpriteWidget):
    def __init__(self, bin_path: str):
        super().__init__("bench_widget", 0, 0, 0, matrix=[])
        self.file_obj = open(bin_path, "rb")
        self.mm = mmap.mmap(self.file_obj.fileno(), 0, access=mmap.ACCESS_READ)

        header = self.mm[:16]
        magic, self.width, self.height, self.total_frames, self.frame_duration = (
            struct.unpack(">4sHHIf", header)
        )

        if magic != b"SPRT":
            raise ValueError("Invalid magic bytes in binary sprite file.")

        self.frame_byte_size = self.width * self.height * 11

        # Pre-allocated matrix (Pool)
        self.matrix = [
            [
                {"char": None, "fg": None, "bg": None, "style": 0}
                for _ in range(self.width)
            ]
            for _ in range(self.height)
        ]

    def decode_frame(self, frame_idx: int):
        offset = 16 + (frame_idx * self.frame_byte_size)
        mv = memoryview(self.mm)[offset : offset + self.frame_byte_size]
        cells = struct.iter_unpack(">IBBBBBBB", mv)
        chr_func = chr

        for row in self.matrix:
            for cell in row:
                c, r1, g1, b1, r2, g2, b2, flags = next(cells)

                if flags == 0:
                    cell["char"] = None
                    cell["fg"] = None
                    cell["bg"] = None
                elif flags == 1:
                    cell["char"] = chr_func(c)
                    cell["fg"] = (r1, g1, b1)
                    cell["bg"] = None
                else:  # flags == 3
                    cell["char"] = chr_func(c)
                    cell["fg"] = (r1, g1, b1)
                    cell["bg"] = (r2, g2, b2)

    def close(self):
        self.mm.close()
        self.file_obj.close()


# --- Benchmark Suite ---
def run_benchmark(bin_path: str, iterations: int):
    widget = BenchmarkSpriteWidget(bin_path)
    canvas = TerminalCanvas(widget.width, widget.height)
    print(f"{type(canvas).__name__}")
    config = {}

    total_cells_per_frame = widget.width * widget.height
    print(f"Loaded File       : {os.path.basename(bin_path)}")
    print(
        f"Grid Resolution   : {widget.width}x{widget.height} ({total_cells_per_frame:,} cells/frame)"
    )
    print(f"Total Frames      : {widget.total_frames}")
    print(f"Iterations / Test : {iterations}\n" + "=" * 55)

    # -------------------------------------------------------------
    # Stage 1: Decoding Only (Binary -> In-Place Matrix)
    # -------------------------------------------------------------
    start_time = time.perf_counter()
    for i in range(iterations):
        frame_idx = i % widget.total_frames
        widget.decode_frame(frame_idx)
    decode_duration = time.perf_counter() - start_time

    decode_fps = iterations / decode_duration
    decode_ms = (decode_duration / iterations) * 1000

    # -------------------------------------------------------------
    # Stage 2: Drawing Only (Matrix -> Canvas Merge)
    # -------------------------------------------------------------
    # Decode once so we have a populated matrix
    widget.decode_frame(0)

    start_time = time.perf_counter()
    for _ in range(iterations):
        widget.draw(canvas, config)
    draw_duration = time.perf_counter() - start_time

    draw_fps = iterations / draw_duration
    draw_ms = (draw_duration / iterations) * 1000

    # -------------------------------------------------------------
    # Stage 3: Combined Full Pipeline (Decode + Draw)
    # -------------------------------------------------------------
    start_time = time.perf_counter()
    for i in range(iterations):
        frame_idx = i % widget.total_frames
        widget.decode_frame(frame_idx)
        widget.draw(canvas, config)
    full_duration = time.perf_counter() - start_time

    full_fps = iterations / full_duration
    full_ms = (full_duration / iterations) * 1000

    widget.close()

    # -------------------------------------------------------------
    # Results Breakdown
    # -------------------------------------------------------------
    print(f"{'Stage':<25} | {'Latency / Frame':<18} | {'Theoretical Max FPS'}")
    print("-" * 65)
    print(
        f"{'1. Binary Decoding':<25} | {decode_ms:8.3f} ms        | {decode_fps:8.1f} FPS"
    )
    print(f"{'2. Matrix Drawing':<25} | {draw_ms:8.3f} ms        | {draw_fps:8.1f} FPS")
    print("-" * 65)
    print(
        f"{'3. Combined Pipeline':<25} | {full_ms:8.3f} ms        | {full_fps:8.1f} FPS"
    )
    print("=" * 65)

    # Bottleneck Analysis
    draw_pct = (draw_ms / full_ms) * 100
    decode_pct = (decode_ms / full_ms) * 100
    print("\n[Bottleneck Analysis]")
    print(f" - Decoding overhead : {decode_pct:.1f}% of frame time")
    print(f" - Drawing overhead  : {draw_pct:.1f}% of frame time")

    if draw_pct > 70:
        print(
            "\n--> BOTTLENECK DETECTED IN DRAWING: The canvas cell lookups (.get()) "
            "and dictionary method calls inside TransparentSpriteWidget.draw() "
            "are consuming most of your frame time."
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Benchmark Terminal Animation Engine Stages"
    )
    parser.add_argument("-i", "--input", required=True, help="Path to .bin file")
    parser.add_argument(
        "-n",
        "--iterations",
        type=int,
        default=500,
        help="Number of iterations per test pass",
    )

    args = parser.parse_args()
    run_benchmark(args.input, args.iterations)
