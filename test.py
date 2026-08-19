import json
from math import ceil

from gleaf import TerminalCanvas
from PIL import Image

from img2sprite import convert_image_to_sprite
from sprites import TransparentSpriteWidget

ASSET = "assets/glavenus.png"

w, h = Image.open(ASSET).size
canvas = TerminalCanvas(w, ceil(h / 2), backend="pure")

with open("config.json") as f:
    config = json.load(f)


TransparentSpriteWidget("test", 0, 0, 0, convert_image_to_sprite(ASSET, w)).draw(
    canvas, config
)
print(canvas.render_ansi_sequence(canvas.render(compute_only=True), w, ceil(h / 2)))
# canvas.render()
print(type(canvas).mro())
