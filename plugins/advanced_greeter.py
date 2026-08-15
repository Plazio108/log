import time
import pwd
import json
import os
import logging
from engine import BaseWidget
from sprites import TransparentSpriteWidget
from gleaf.styles import Modifiers
from oakey.listener import Keys

# Set up plugin logger
logger = logging.getLogger("plugin.advanced_greeter")

# ==========================================
# PLUGIN WIDGETS
# ==========================================
class BigClockWidget(BaseWidget):
    def __init__(self, config: dict):
        super().__init__("big_clock", "center", 2, config["layout"]["z_ui_base"])
        # A simple 3x5 font for digits (using █ for solid blocks)
        self.font = {
            "0": ["███", "█ █", "█ █", "█ █", "███"],
            "1": [" ██", "  █", "  █", "  █", " ██"],
            "2": ["███", "  █", "███", "█  ", "███"],
            "3": ["███", "  █", "███", "  █", "███"],
            "4": ["█ █", "█ █", "███", "  █", "  █"],
            "5": ["███", "█  ", "███", "  █", "███"],
            "6": ["███", "█  ", "███", "█ █", "███"],
            "7": ["███", "  █", "  █", "  █", "  █"],
            "8": ["███", "█ █", "███", "█ █", "███"],
            "9": ["███", "█ █", "███", "  █", "███"],
            ":": ["   ", " █ ", "   ", " █ ", "   "],
        }
        self.time_str = ""
        self.matrix = []

    def update(self, dt: float, engine):
        new_time = time.strftime("%H:%M")
        if new_time != self.time_str:
            self.time_str = new_time
            self._build_matrix(engine.config)

    def _build_matrix(self, config):
        self.matrix = [[] for _ in range(5)]
        for char in self.time_str:
            art = self.font.get(char, ["   "] * 5)
            for y in range(5):
                for pixel in art[y]:
                    bg = config["theme"]["text_accent"] if pixel == "█" else None
                    self.matrix[y].append(
                        {"char": None, "fg": None, "bg": bg, "style": None}
                    )
                self.matrix[y].append(
                    {"char": None, "fg": None, "bg": None, "style": None}
                )

    def draw(self, canvas, config):
        w = len(self.matrix[0]) if self.matrix else 0
        c_x, c_y = self.get_coords(canvas, w, 5, config)
        TransparentSpriteWidget("temp", c_x, c_y, 0, self.matrix).draw(canvas, config)


class UserProfileCycler(BaseWidget):
    """
    Acts exactly like an InputWidget for the engine's API, but handles
    cycler logic using LEFT/RIGHT keys. Inherits the name "input_user".
    """

    def __init__(self, config: dict):
        super().__init__(
            "input_user",
            config["layout"]["box_x"],
            config["layout"]["box_y"],
            config["layout"]["z_ui_elements"],
        )
        self.focusable = True

        self.users = [u.pw_name for u in pwd.getpwall() if 1000 <= u.pw_uid < 65534]
        if not self.users:
            self.users = ["guest"]
        self.current_idx = 0

        # Fulfill the InputWidget API so AuthLogicWidget can read this property
        self.value = self.users[self.current_idx]

    def handle_key(self, key: str, engine) -> bool:
        if key == Keys.LEFT:
            self.current_idx = (self.current_idx - 1) % len(self.users)
            self._apply_user_profile(engine)
            return True
        elif key == Keys.RIGHT:
            self.current_idx = (self.current_idx + 1) % len(self.users)
            self._apply_user_profile(engine)
            return True
        return False  # Ignore other keys

    def _apply_user_profile(self, engine):
        self.value = self.users[self.current_idx]
        cfg_path = f"/etc/greeter/users/{self.value}.json"
        
        logger.debug(f"Cycling to user profile: {self.value}")

        if os.path.exists(cfg_path):
            try:
                with open(cfg_path, "r") as f:
                    engine.config["theme"].update(json.load(f))
                    logger.debug(f"Loaded custom theme for user: {self.value}")
            except Exception as e:
                logger.error(f"Failed to load theme for {self.value}: {e}")
        else:
            engine.config["theme"]["text_accent"] = (100, 200, 255)  # Fallback
            logger.debug(f"No custom theme found for {self.value}, using fallback.")

        icon_widget = engine.get_widget("profile_icon")
        if icon_widget:
            icon_widget.load_avatar(self.value)
            
        # This force_draw is now safe because the engine enters the
        # alternate screen BEFORE loading plugins.
        engine.force_draw()

    def draw(self, canvas, config):
        lyt, thm = config["layout"], config["theme"]
        c_x, c_y = self.get_coords(canvas, lyt["box_width"], lyt["box_height"], config)
        div = config["engine"]["math_center_divisor"]

        display_text = f"< {self.value} >"
        color = thm["text_accent"] if self.focused else thm["text_main"]

        # Center the cycler horizontally inside the box
        text_x = c_x + (lyt["box_width"] // div) - (len(display_text) // div)
        canvas.put_str(
            text_x,
            c_y + lyt["user_y_offset"],
            display_text,
            color,
            thm["box_bg"],
            Modifiers.BOLD,
            None,
        )


class ProfileIconWidget(TransparentSpriteWidget):
    def __init__(self, config: dict):
        super().__init__(
            "profile_icon",
            config["layout"]["box_x"],
            config["layout"]["box_y"],
            config["layout"]["z_ui_elements"],
            matrix=[],
        )
        self.load_avatar("default")

    def load_avatar(self, username: str):
        path = f"/etc/greeter/icons/{username}.json"
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    self.matrix = json.load(f)
                    logger.debug(f"Loaded avatar for {username}")
            except Exception as e:
                logger.error(f"Failed to load avatar json for {username}: {e}")
                self._load_fallback()
        else:
            self._load_fallback()
            
    def _load_fallback(self):
        # Fallback 3x3 yellow block smiley
        self.matrix = [
            [{"char": "▀", "fg": (255, 255, 0), "bg": None, "style": 0}] * 6,
            [
                {"char": ".", "fg": (0, 0, 0), "bg": (255, 255, 0), "style": 0},
                {"char": None, "fg": None, "bg": None, "style": None},
                {"char": ".", "fg": (0, 0, 0), "bg": (255, 255, 0), "style": 0},
            ],
            [{"char": "▄", "fg": (255, 255, 0), "bg": None, "style": 0}] * 6,
        ]

    def draw(self, canvas, config):
        lyt = config["layout"]
        div = config["engine"]["math_center_divisor"]
        box_x, box_y = self.get_coords(
            canvas, lyt["box_width"], lyt["box_height"], config
        )

        w = len(self.matrix[0]) if self.matrix else 0
        icon_x = box_x + (lyt["box_width"] // div) - (w // div)
        icon_y = box_y + lyt["icon_y_offset"]

        TransparentSpriteWidget("temp", icon_x, icon_y, 0, self.matrix).draw(
            canvas, config
        )


# ==========================================
# PLUGIN INJECTION ROUTINE
# ==========================================
def setup(engine):
    logger.info("Initializing advanced_greeter plugin")
    
    # 1. Modify Layout
    engine.config["layout"].update(
        {
            "box_height": 20,
            "title_y_offset": 1,
            "icon_y_offset": 4,   # Icon sits under title
            "user_y_offset": 10,  # Cycler sits under icon
            "pass_y_offset": 14,  # Password field under cycler
            "msg_y_offset": 17,   # Messages at the bottom
        }
    )

    # 2. Swap out the default Username field for the Cycler
    engine.remove_widget("input_user")
    cycler = UserProfileCycler(engine.config)
    engine.add_widget(cycler)

    # 3. Add the Clock and Icon
    engine.add_widget(ProfileIconWidget(engine.config))
    engine.add_widget(BigClockWidget(engine.config))

    # Trigger an initial avatar/theme sync
    cycler._apply_user_profile(engine)

    # Ensure focus resets to our new cycler widget
    engine._cycle_focus(reverse=False)
