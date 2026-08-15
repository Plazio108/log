import json

from gleaf import TerminalCanvas

from img2sprite import convert_image_to_sprite
from sprites import TransparentSpriteWidget

canvas = TerminalCanvas(backend="pure")

with open("config.json") as f:
    config = json.load(f)

TransparentSpriteWidget(
    "test", 0, 0, 0, convert_image_to_sprite("assets/charmander.png", 21)
).draw(canvas, config)
canvas.render()
