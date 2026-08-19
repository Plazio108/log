from gleaf import BaseCanvas

from engine import BaseWidget

import logging

logger = logging.getLogger("plugin.animated_sprite")


class TransparentSpriteWidget(BaseWidget):
    """Renders a custom matrix format with true transparency support."""

    def __init__(self, name: str, x, y, z_index: int, matrix: list):
        super().__init__(name, x, y, z_index)
        self.matrix = matrix

    def draw(self, canvas: BaseCanvas, config: dict):
        # Calculate width/height from the matrix
        w = len(self.matrix[0]) if self.matrix else 0
        h = len(self.matrix)
        start_x, start_y = self.get_coords(canvas, w, h, config)

        for dy, row in enumerate(self.matrix):
            for dx, cell in enumerate(row):
                if not cell:
                    continue  # Skip empty data

                c_x = start_x + dx
                c_y = start_y + dy

                # Fetch what is currently on the canvas at this layer
                old_char, old_fg, old_bg, old_style = canvas.get_cell(c_x, c_y)

                # Merge new values, falling back to old values if None
                new_char = cell.get("char")
                new_char = new_char if new_char is not None else old_char

                new_fg = cell.get("fg")
                new_fg = tuple(new_fg) if new_fg else old_fg

                new_bg = cell.get("bg")
                new_bg = tuple(new_bg) if new_bg else old_bg

                new_style = cell.get("style")
                new_style = new_style if new_style is not None else old_style

                canvas.put_str(c_x, c_y, new_char, new_fg, new_bg, new_style)


import json
import os


class AnimatedSpriteWidget(TransparentSpriteWidget):
    """
    Renders multi-frame JSON animations driven by delta-time updates.

    JSON Schema:
    {
        "loop": true,
        "frames": [
            {
                "duration": 0.15,
                "matrix": [ [ {"char": "a", "fg": [255,0,0], "bg": null, "style": 0}, ... ] ]
            }
        ]
    }
    """

    def __init__(
        self,
        name: str,
        x: int | str,
        y: int | str,
        z_index: int,
        json_path: str | None = None,
        loop: bool = True,
    ):
        super().__init__(name, x, y, z_index, matrix=[])
        self.frames: list[dict] = []
        self.current_frame_idx = 0
        self.elapsed = 0.0
        self.loop = loop
        self.playing = True

        if json_path:
            self.load_animation(json_path)

    def load_animation(self, json_path: str | dict):
        if isinstance(json_path, str) and not os.path.exists(json_path):
            logger.error(f"Animation file not found: {json_path}")
            self._load_fallback()
            return

        try:
            if isinstance(json_path, str):
                with open(json_path, "r") as f:
                    data = json.load(f)
            else:
                data = json_path

            self.loop = data.get("loop", self.loop)
            raw_frames = data.get("frames", [])

            processed_frames = []
            for frame in raw_frames:
                dur = float(frame.get("duration", 0.1))
                raw_mat = frame.get("matrix", [])

                # Standardize JSON list colors [r, g, b] into Python tuples (r, g, b)
                clean_mat = []
                for row in raw_mat:
                    clean_row = []
                    for cell in row:
                        fg = (
                            tuple(cell["fg"])
                            if isinstance(cell.get("fg"), list)
                            else cell.get("fg")
                        )
                        bg = (
                            tuple(cell["bg"])
                            if isinstance(cell.get("bg"), list)
                            else cell.get("bg")
                        )
                        clean_row.append(
                            {
                                "char": cell.get("char"),
                                "fg": fg,
                                "bg": bg,
                                "style": cell.get("style"),
                            }
                        )
                    clean_mat.append(clean_row)
                processed_frames.append({"duration": dur, "matrix": clean_mat})

            self.frames = processed_frames
            if self.frames:
                self.current_frame_idx = 0
                self.elapsed = 0.0
                self.matrix = self.frames[0]["matrix"]
                self.playing = True
                logger.debug(f"Loaded {len(self.frames)} frames from {json_path}")
            else:
                self._load_fallback()

        except Exception as e:
            logger.error(f"Failed to parse animation JSON '{json_path}': {e}")
            self._load_fallback()

    def _load_fallback(self):
        # 2x2 fallback warning block
        self.matrix = [
            [{"char": "!", "fg": (255, 0, 0), "bg": None, "style": 1}] * 2,
            [{"char": "!", "fg": (255, 0, 0), "bg": None, "style": 1}] * 2,
        ]
        self.frames = [{"duration": 1.0, "matrix": self.matrix}]
        self.playing = False

    def update(self, dt: float, engine):
        if not self.playing or not self.frames:
            return

        self.elapsed += dt
        current_frame = self.frames[self.current_frame_idx]
        frame_dur = current_frame["duration"]

        if self.elapsed >= frame_dur:
            self.elapsed -= frame_dur
            self.current_frame_idx += 1

            if self.current_frame_idx >= len(self.frames):
                if self.loop:
                    self.current_frame_idx = 0
                else:
                    self.current_frame_idx = len(self.frames) - 1
                    self.playing = False

            # Update the active display matrix for TransparentSpriteWidget.draw()
            self.matrix = self.frames[self.current_frame_idx]["matrix"]

    def play(self):
        self.playing = True

    def pause(self):
        self.playing = False

    def stop(self):
        self.playing = False
        self.current_frame_idx = 0
        self.elapsed = 0.0
        if self.frames:
            self.matrix = self.frames[0]["matrix"]
