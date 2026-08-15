from gleaf import BaseCanvas

from engine import BaseWidget


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
