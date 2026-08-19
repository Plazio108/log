import logging
import mmap
import struct
import time

import lz4.block
from gleaf import UNSET, BaseCanvas, TerminalTexture

from engine import BACKEND, BaseWidget

logger = logging.getLogger("plugin.sprites")


class TransparentSpriteWidget(BaseWidget):
    """
    Renders an off-screen matrix, .bin file, or raw uncompressed texture bytes.
    Backward compatible with legacy list-of-dicts matrix formatting.
    """

    def __init__(
        self,
        name: str,
        x,
        y,
        z_index: int,
        matrix: list | None = None,
        bin_path: str | None = None,
        raw_bytes: bytes | None = None,
        width: int | None = None,
        height: int | None = None,
    ):
        super().__init__(name, x, y, z_index)
        self.texture = None

        if raw_bytes:
            if width is None or height is None:
                raise ValueError(
                    "Both 'width' and 'height' are required when passing 'raw_bytes'."
                )
            self.texture = TerminalTexture(
                width, height, data_buffer=raw_bytes, backend=BACKEND
            )

        elif bin_path:
            # Reads the SPRT format and grabs just the first frame
            with open(bin_path, "rb") as f:
                header = f.read(16)
                if header.startswith(b"SPRT"):
                    _, w, h, _, _ = struct.unpack(">4sHHIf", header)
                    comp_size = struct.unpack(">I", f.read(4))[0]
                    compressed_frame = f.read(comp_size)

                    uncompressed_bytes = lz4.block.decompress(
                        compressed_frame, uncompressed_size=w * h * 24
                    )
                    self.texture = TerminalTexture(
                        w, h, data_buffer=uncompressed_bytes, backend=BACKEND
                    )
                else:
                    raise ValueError(f"Invalid SPRT header in {bin_path}")

        elif matrix:
            # Backward compatibility: manually parse legacy list of dicts
            h = len(matrix)
            w = len(matrix[0]) if h > 0 else 0
            self.texture = TerminalTexture(w, h, backend=BACKEND)

            for cy, row in enumerate(matrix):
                for cx, cell in enumerate(row):
                    if not cell:
                        continue

                    c_char = cell.get("char")
                    c_fg = cell.get("fg")
                    c_bg = cell.get("bg")

                    # 1. Detect fully transparent cell (all nulls)
                    if c_char is None and c_fg is None and c_bg is None:
                        # Leave the texture cell at EMPTY_CELL (ch=0, mode=0).
                        # When blitted, it won't touch the canvas below.
                        continue

                    # 2. Extract values gracefully
                    ch = c_char if c_char is not None else " "

                    # 3. Use UNSET instead of None so the renderer treats it as transparent
                    #    rather than a command to "CLEAR" the background.
                    fg = tuple(c_fg) if c_fg else UNSET
                    bg = tuple(c_bg) if c_bg else UNSET
                    style = (
                        cell.get("style") if cell.get("style") is not None else UNSET
                    )

                    self.texture.put_str(cx, cy, ch, fg=fg, bg=bg, style=style)

    def draw(self, canvas: BaseCanvas, config: dict):
        if not self.texture:
            return

        self.texture.apply_to(canvas, self.left, self.top)

    @property
    def w(self):
        if not self.texture:
            return 0
        return self.texture.width

    @property
    def h(self):
        if not self.texture:
            return 0
        return self.texture.height


class AnimatedSpriteWidget(TransparentSpriteWidget):
    """
    Renders an animated .bin SPRT file.
    Uses memory mapping (mmap) and on-the-fly LZ4 uncompression for performance.
    """

    def __init__(self, name: str, x, y, z_index: int, bin_path: str):
        super().__init__(name, x, y, z_index)

        self.bin_path = bin_path
        self.file_obj = open(bin_path, "rb")
        self.mmap_obj = mmap.mmap(self.file_obj.fileno(), 0, access=mmap.ACCESS_READ)

        header = self.mmap_obj[:16]
        if not header.startswith(b"SPRT"):
            raise ValueError(f"Invalid SPRT binary format in {bin_path}")

        _, self.width, self.height, self.total_frames, self.duration = struct.unpack(
            ">4sHHIf", header
        )

        self._uncompressed_size = self.width * self.height * 24

        # Pre-calculate frame offsets for O(1) random-access seeking
        self.frame_offsets = []
        offset = 16
        for _ in range(self.total_frames):
            self.frame_offsets.append(offset)
            comp_size = struct.unpack(">I", self.mmap_obj[offset : offset + 4])[0]
            offset += 4 + comp_size

        self.current_frame = -1
        self.start_time = time.time()

        if self.total_frames > 0:
            self._live_load_frame(0)

    def _live_load_frame(self, frame_idx: int):
        """Extracts block from mmap, decompresses LZ4 payload, loads into TerminalTexture."""
        offset = self.frame_offsets[frame_idx]

        comp_size = struct.unpack(">I", self.mmap_obj[offset : offset + 4])[0]
        compressed_bytes = self.mmap_obj[offset + 4 : offset + 4 + comp_size]

        uncompressed_bytes = lz4.block.decompress(
            compressed_bytes, uncompressed_size=self._uncompressed_size
        )

        self.texture = TerminalTexture(
            self.width, self.height, data_buffer=uncompressed_bytes, backend=BACKEND
        )
        self.current_frame = frame_idx

    def draw(self, canvas: BaseCanvas, config: dict):
        if self.total_frames > 0 and self.duration > 0:
            elapsed = time.time() - self.start_time
            target_frame = int(elapsed / self.duration) % self.total_frames

            if target_frame != self.current_frame:
                self._live_load_frame(target_frame)

        super().draw(canvas, config)

    def close(self):
        """Call during cleanup/shutdown to release mapped file descriptor."""
        if hasattr(self, "mmap_obj"):
            self.mmap_obj.close()
            self.file_obj.close()
