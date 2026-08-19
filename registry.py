# Global registry so the parser can find named widgets without passing 'engine'
from typing import ClassVar

from gleaf import BaseCanvas


class UIRegistry:
    widgets: ClassVar = {}
    canvas: ClassVar[BaseCanvas] = None

    @classmethod
    def register(cls, name, widget):
        cls.widgets[name] = widget

    @classmethod
    def set_canvas(cls, canvas):
        cls.canvas = canvas
