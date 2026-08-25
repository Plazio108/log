import importlib.util
import json
import logging
import os
import pwd

from gleaf.styles import Modifiers
from oakey.listener import Keys

from engine import BaseWidget
from sprites import TransparentSpriteWidget

# Set up plugin logger
logger = logging.getLogger("plugin.advanced_greeter")


# ==========================================
# PLUGIN WIDGETS
# ==========================================


def get_user_list():
    users = [u.pw_name for u in pwd.getpwall() if 1000 <= u.pw_uid < 65534]
    return users if users else ["guest"]


class UserProfileCycler(BaseWidget):
    """
    Acts exactly like an InputWidget for the engine's API, but handles
    cycler logic using LEFT/RIGHT keys. Inherits the name "input_user".
    """

    def __init__(self, config: dict):
        super().__init__(
            "input_user",
            config["layout"]["user_x"],
            config["layout"]["user_y"],
            config["layout"]["z_ui_elements"],
        )
        self.focusable = True

        self.users = get_user_list()
        self.current_idx = config.get("__active_user_idx", 0)

        # Fulfill the InputWidget API so AuthLogicWidget can read this property
        self.value = self.users[self.current_idx]

    def handle_key(self, key: str, engine) -> bool:
        if key in (Keys.LEFT, Keys.RIGHT):
            if key == Keys.LEFT:
                self.current_idx = (self.current_idx - 1) % len(self.users)
            else:
                self.current_idx = (self.current_idx + 1) % len(self.users)

            self.value = self.users[self.current_idx]

            # --- THE CRITICAL STEP ---
            # Save the new index to the PRISTINE config backup so it survives the engine reload
            engine.original_config["__active_user_idx"] = self.current_idx

            # Trigger hot reload (wipes UI, resolves user theme, rebuilds UI)
            engine.reload_plugins()
            return True
        return False

    # def _apply_user_profile(self, engine):
    #     self.value = self.users[self.current_idx]
    #     cfg_path = f"/etc/greeter/users/{self.value}.json"

    #     logger.debug(f"Cycling to user profile: {self.value}")

    #     if os.path.exists(cfg_path):
    #         try:
    #             with open(cfg_path, "r") as f:
    #                 engine.config["theme"].update(json.load(f))
    #                 logger.debug(f"Loaded custom theme for user: {self.value}")
    #         except Exception as e:
    #             logger.error(f"Failed to load theme for {self.value}: {e}")
    #     else:
    #         engine.config["theme"]["text_accent"] = (100, 200, 255)  # Fallback
    #         logger.debug(f"No custom theme found for {self.value}, using fallback.")

    #     icon_widget = engine.get_widget("profile_icon")
    #     if icon_widget:
    #         icon_widget.load_avatar(self.value)

    #     # This force_draw is now safe because the engine enters the
    #     # alternate screen BEFORE loading plugins.
    #     engine.force_draw()

    def draw(self, canvas, config):
        thm = config["theme"]

        color = thm["text_accent"] if self.focused else thm["text_main"]

        # Center the cycler horizontally inside the box
        canvas.put_str(
            self.left,
            self.centery,
            self.value,
            color,
            style=Modifiers.BOLD,
        )

        previous = config["profile_selector"]["previous"]
        canvas.put_str(
            self.left - len(previous),
            self.centery,
            previous,
            color,
            style=Modifiers.BOLD,
        )

        next = config["profile_selector"]["next"]
        canvas.put_str(self.right + 1, self.centery, next, color, style=Modifiers.BOLD)

    @property
    def w(self):
        return len(self.value)


class ProfileIconWidget(TransparentSpriteWidget):
    def __init__(self, config: dict):
        super().__init__(
            "profile_icon",
            config["profile_selector"]["icon_x"],
            config["profile_selector"]["icon_y"],
            config["layout"]["z_ui_elements"],
            matrix=[],
        )
        username = config.get("__active_username", "default")
        self.load_avatar(username)

    def load_avatar(self, username: str):
        path = f"/usr/share/log/icons/{username}.json"
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

        TransparentSpriteWidget(
            None, self.left, self.top, self.z_index, self.matrix
        ).draw(canvas, config)

    @property
    def w(self):
        return len(self.matrix[0]) if self.matrix else 0

    @property
    def h(self):
        return len(self.matrix) if self.matrix else 0


def config(config):
    logger.info("Profile Selector Configuration...")

    config["layout"].update(
        {
            "box_height": 24,
            "user_x": "box_bg.centerx",
            "user_y": "profile_icon.bottom+2",
            "pass_x": "box_bg.centerx",
            "pass_y": "input_user.bottom+3",
        }
    )

    config["profile_selector"] = {
        "previous": "< ",
        "next": " >",
        "icon_x": "box_bg.centerx",
        "icon_y": "title.bottom+2",
    }

    config["anchors"].update({"profile_icon": "n", "input_user": "center"})

    users = get_user_list()
    active_idx = config.get("__active_user_idx", 0)

    if active_idx >= len(users):
        active_idx = 0

    active_user = users[active_idx]

    # Store string name for widgets to consume
    config["__active_username"] = active_user

    # 3. Ensure the overrides list exists
    if "__overrides" not in config:
        config["__overrides"] = []

    # 4. Load the user's Python config file dynamically
    cfg_path = f"/usr/share/log/users/{active_user}_config.py"

    if os.path.exists(cfg_path):
        try:
            # Dynamically import the user's config file
            spec = importlib.util.spec_from_file_location(
                f"{active_user}_config", cfg_path
            )
            if spec and spec.loader:
                user_module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(user_module)

                # Check if the file actually defines USER_CONFIG
                if hasattr(user_module, "USER_CONFIG"):
                    # Append the dictionary to the overrides list
                    config["__overrides"].append(user_module.USER_CONFIG)
                    logger.debug(
                        f"Appended deferred config overrides for user: {active_user}"
                    )
                else:
                    logger.warning(
                        f"{cfg_path} exists but has no USER_CONFIG dictionary defined."
                    )
        except Exception as e:
            logger.error(f"Failed to load theme for {active_user}: {e}")

    logger.info("Profile Selector configurated")


# ==========================================
# PLUGIN INJECTION ROUTINE
# ==========================================
def setup(engine):
    logger.info("Initializing advanced_greeter plugin")

    # 1. Modify Layout

    # 2. Swap out the default Username field for the Cycler
    engine.remove_widget("input_user")
    cycler = UserProfileCycler(engine.config)
    engine.add_widget(cycler)

    # 3. Add the Clock and Icon
    engine.add_widget(ProfileIconWidget(engine.config))

    # Ensure focus resets to our new cycler widget
    engine._cycle_focus(reverse=False)
