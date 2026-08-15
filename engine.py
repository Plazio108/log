import importlib.util
import json
import logging
import time
from typing import cast

from gleaf import BaseCanvas, TerminalCanvas
from gleaf.styles import Modifiers
from oakey import Empty, KeyListener, Keys

from greetd_ipc import GreetdClient, GreetdError

# ==========================================
# 0. LOGGING SETUP
# ==========================================
logging.basicConfig(
    filename="/tmp/standalone-dm.log",
    filemode="a",
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.DEBUG,
)
logger = logging.getLogger("engine")

# ==========================================
# 1. THE OMNI-CONFIG
# ==========================================

# with open("config.json") as conf:
#     CONFIG = json.load(conf)

CONFIG = {
    "engine": {
        "target_fps": 30,
        "input_timeout": 0.05,
        "math_center_divisor": 2,
        "plugins": ["advanced_greeter"],
    },
    "theme": {
        "bg_color": (15, 15, 20),
        "box_bg": (30, 30, 40),
        "text_main": (220, 220, 220),
        "text_accent": (255, 100, 100),
        "text_error": (255, 80, 80),
        "text_success": (80, 255, 80),
    },
    "layout": {
        "z_background": 0,
        "z_ui_base": 4,
        "z_ui_elements": 5,
        "z_overlay": 10,
        "box_width": 44,
        "box_height": 14,
        "box_x": "center",
        "box_y": "center",
        "title_y_offset": 2,
        "user_y_offset": 6,
        "pass_y_offset": 8,
        "msg_y_offset": 11,
        "x_padding": 4,
    },
    "text": {
        "title": " standalone-dm ",
        "user_active": "> user: ",
        "user_idle": "  user: ",
        "pass_active": "> pass: ",
        "pass_idle": "  pass: ",
        "mask_char": "*",
        "msg_authenticating": "Authenticating...",
        "msg_success": "Login successful. Starting...",
        "msg_fail": "Authentication failed.",
    },
    "system": {"default_session_cmd": ["Hyprland"], "empty_string": ""},
}


# ==========================================
# 2. WIDGET BASE CLASS
# ==========================================
class BaseWidget:
    def __init__(self, name: str, x: int | str, y: int | str, z_index: int):
        self.name = name
        self.x_raw = x
        self.y_raw = y
        self.z_index = z_index
        self.focusable = False
        self.focused = False
        self.visible = True
        self.value = ""

    def get_coords(
        self, canvas: BaseCanvas, w: int, h: int, config: dict
    ) -> tuple[int, int]:
        div = config["engine"]["math_center_divisor"]
        x = (
            (canvas.width // div) - (w // div)
            if self.x_raw == "center"
            else int(self.x_raw)
        )
        y = (
            (canvas.height // div) - (h // div)
            if self.y_raw == "center"
            else int(self.y_raw)
        )
        return x, y

    def update(self, dt: float, engine: "GreeterEngine"):
        pass

    def draw(self, canvas: BaseCanvas, config: dict):
        pass

    def handle_key(self, key: str, engine: "GreeterEngine") -> bool:
        return False


# ==========================================
# 3. MODULAR DEFAULT WIDGETS
# ==========================================
class DefaultBackground(BaseWidget):
    def __init__(self, config: dict):
        super().__init__("default_bg", 0, 0, config["layout"]["z_background"])

    def draw(self, canvas, config):
        canvas.edit_region_colors(
            self.x_raw,
            self.y_raw,
            canvas.width,
            canvas.height,
            None,
            config["theme"]["bg_color"],
        )


class BoxBackgroundWidget(BaseWidget):
    """Draws the static box and title."""

    def __init__(self, config: dict):
        super().__init__(
            "box_bg",
            config["layout"]["box_x"],
            config["layout"]["box_y"],
            config["layout"]["z_ui_base"],
        )

    def draw(self, canvas, config):
        lyt, txt, thm = config["layout"], config["text"], config["theme"]
        c_x, c_y = self.get_coords(canvas, lyt["box_width"], lyt["box_height"], config)
        div = config["engine"]["math_center_divisor"]

        canvas.edit_region_colors(
            c_x, c_y, lyt["box_width"], lyt["box_height"], None, thm["box_bg"]
        )
        title_x = c_x + (lyt["box_width"] // div) - (len(txt["title"]) // div)
        canvas.put_str(
            title_x,
            c_y + lyt["title_y_offset"],
            txt["title"],
            thm["text_main"],
            thm["box_bg"],
            Modifiers.BOLD,
            None,
        )


class InputWidget(BaseWidget):
    """A highly reusable text input field."""

    def __init__(
        self,
        name: str,
        y_offset_key: str,
        label_active_key: str,
        label_idle_key: str,
        is_password: bool,
        config: dict,
    ):
        super().__init__(
            name,
            config["layout"]["box_x"],
            config["layout"]["box_y"],
            config["layout"]["z_ui_elements"],
        )
        self.focusable = True
        self.is_password = is_password
        self.y_offset_key = y_offset_key
        self.label_active_key = label_active_key
        self.label_idle_key = label_idle_key

    def handle_key(self, key: str, engine) -> bool:
        if key == Keys.BACKSPACE:
            self.value = self.value[:-1]
            return True
        elif len(key) == 1 and key.isprintable():
            self.value += key
            # Clear auth messages on new typing
            auth_logic = engine.get_widget("auth_logic")
            if auth_logic:
                auth_logic.sys_msg = engine.config["system"]["empty_string"]
            return True
        return False

    def draw(self, canvas, config):
        lyt, txt, thm = config["layout"], config["text"], config["theme"]
        c_x, c_y = self.get_coords(canvas, lyt["box_width"], lyt["box_height"], config)

        lbl = txt[self.label_active_key] if self.focused else txt[self.label_idle_key]
        col = thm["text_accent"] if self.focused else thm["text_main"]
        disp_val = (
            (txt["mask_char"] * len(self.value)) if self.is_password else self.value
        )

        canvas.put_str(
            c_x + lyt["x_padding"],
            c_y + lyt[self.y_offset_key],
            f"{lbl}{disp_val}",
            col,
            thm["box_bg"],
            Modifiers.NONE,
            None,
        )


class AuthLogicWidget(BaseWidget):
    """Invisible logic controller that handles ENTER keys and renders system messages."""

    def __init__(self, config: dict):
        super().__init__(
            "auth_logic",
            config["layout"]["box_x"],
            config["layout"]["box_y"],
            config["layout"]["z_ui_elements"],
        )
        self.sys_msg = config["system"]["empty_string"]
        self.msg_is_error = False

    def draw(self, canvas, config):
        if not self.sys_msg:
            return
        lyt, thm = config["layout"], config["theme"]
        c_x, c_y = self.get_coords(canvas, lyt["box_width"], lyt["box_height"], config)
        div = config["engine"]["math_center_divisor"]

        m_col = thm["text_error"] if self.msg_is_error else thm["text_success"]
        msg_x = c_x + (lyt["box_width"] // div) - (len(self.sys_msg) // div)
        canvas.put_str(
            msg_x,
            c_y + lyt["msg_y_offset"],
            self.sys_msg,
            m_col,
            thm["box_bg"],
            Modifiers.BOLD,
            None,
        )

    def attempt_login(self, engine):
        w_user = engine.get_widget("input_user")
        w_pass = engine.get_widget("input_pass")
        if not w_user or not w_pass or not w_user.value or not w_pass.value:
            return

        txt, sys_cfg = engine.config["text"], engine.config["system"]
        self.sys_msg = txt["msg_authenticating"]
        self.msg_is_error = False
        engine.force_draw()

        logger.info(f"Attempting login for user: {w_user.value}")

        try:
            resp = engine.greetd.create_session(w_user.value)
            while resp.get("type") == "auth_message":
                msg_type = resp.get("auth_message_type", "visible")
                if msg_type == "secret":
                    resp = engine.greetd.post_auth_message_response(w_pass.value)
                elif msg_type in ("info", "error"):
                    resp = engine.greetd.post_auth_message_response(None)
                else:
                    resp = engine.greetd.post_auth_message_response(w_user.value)

            if resp.get("type") == "success":
                logger.info(
                    f"Authentication successful for {w_user.value}. Starting session..."
                )
                self.sys_msg = txt["msg_success"]
                engine.force_draw()
                engine.greetd.start_session(cmd=sys_cfg["default_session_cmd"])
                engine.running = False
            else:
                logger.warning(f"Authentication failed for {w_user.value}")
                self._fail(txt["msg_fail"], w_pass, engine)
        except GreetdError as e:
            logger.error(f"Greetd exception during login: {e.description}")
            self._fail(e.description, w_pass, engine)

    def _fail(self, msg: str, pass_widget, engine):
        self.sys_msg = msg
        self.msg_is_error = True
        pass_widget.value = engine.config["system"]["empty_string"]
        engine.greetd.cancel_session()


# ==========================================
# 4. THE CORE ENGINE
# ==========================================
class GreeterEngine:
    def __init__(self, config: dict):
        self.config = config
        self.canvas = TerminalCanvas(width=None, height=None, backend="pure")
        self.greetd = GreetdClient()
        self.widgets: list[BaseWidget] = []
        self.running = True

        self.add_widget(DefaultBackground(self.config))
        self.add_widget(BoxBackgroundWidget(self.config))
        self.add_widget(
            InputWidget(
                "input_user",
                "user_y_offset",
                "user_active",
                "user_idle",
                False,
                self.config,
            )
        )
        self.add_widget(
            InputWidget(
                "input_pass",
                "pass_y_offset",
                "pass_active",
                "pass_idle",
                True,
                self.config,
            )
        )
        self.add_widget(AuthLogicWidget(self.config))

        # Initialize default focus
        focusables = [w for w in self.widgets if w.focusable]
        if focusables:
            focusables[0].focused = True

    def add_widget(self, widget: BaseWidget):
        self.widgets.append(widget)
        self.widgets.sort(key=lambda w: w.z_index)

    def remove_widget(self, name: str):
        self.widgets = [w for w in self.widgets if w.name != name]

    def get_widget(self, name: str) -> BaseWidget | None:
        return next((w for w in self.widgets if w.name == name), None)

    def force_draw(self):
        self.canvas.auto_resize()
        self.canvas.clear()
        for w in self.widgets:
            if w.visible:
                w.draw(self.canvas, self.config)
        self.canvas.render()

    def _cycle_focus(self, reverse=False):
        """Engine-level focus management ensures state never desyncs."""
        focusables = [w for w in self.widgets if w.focusable and w.visible]
        if not focusables:
            return

        current_idx = next((i for i, w in enumerate(focusables) if w.focused), -1)
        if current_idx != -1:
            focusables[current_idx].focused = False

        next_idx = (
            (current_idx - 1) % len(focusables)
            if reverse
            else (current_idx + 1) % len(focusables)
        )
        focusables[next_idx].focused = True

    def _load_plugins(self):
        for plugin_name in self.config["engine"]["plugins"]:
            try:
                logger.info(f"Loading plugin: {plugin_name}")
                spec = importlib.util.spec_from_file_location(
                    plugin_name, f"plugins/{plugin_name}.py"
                )
                if spec and spec.loader:
                    plugin_module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(plugin_module)
                    plugin_module.setup(self)
                    logger.info(f"Plugin {plugin_name} loaded successfully.")
            except Exception as e:
                logger.error(f"Plugin error [{plugin_name}]: {e}", exc_info=True)

    def run(self):
        logger.info("--- Starting GreeterEngine ---")

        # 1. FIX GHOST FRAME: Enter alternate screen BEFORE plugins run setup routines!
        self.canvas.enter_alternate_screen()
        self._load_plugins()

        try:
            self.greetd.connect()
            logger.info("Connected to greetd IPC")
        except Exception as e:
            logger.error(f"Failed to connect to greetd: {e}")

        cfg_eng = self.config["engine"]
        frame_time = 1.0 / cfg_eng["target_fps"]
        last_time = time.time()

        try:
            with KeyListener(suppress_errors=True) as listener:
                while self.running:
                    current_time = time.time()
                    dt = current_time - last_time

                    if dt >= frame_time:
                        last_time = current_time

                        try:
                            key = listener.get(
                                block=False, timeout=cfg_eng["input_timeout"]
                            )
                        except Empty:
                            key = None

                        if key:
                            if key == Keys.ESCAPE:
                                logger.info("ESCAPE pressed, shutting down.")
                                self.running = False
                                break

                            elif key == Keys.TAB:
                                self._cycle_focus(reverse=False)
                            elif key == Keys.SHIFT_TAB:
                                self._cycle_focus(reverse=True)
                            elif key == Keys.ENTER:
                                auth = cast(
                                    AuthLogicWidget, self.get_widget("auth_logic")
                                )
                                if auth:
                                    auth.attempt_login(self)
                            else:
                                for w in reversed(self.widgets):
                                    if (
                                        w.focusable
                                        and w.focused
                                        and w.handle_key(key, self)
                                    ):
                                        break

                        for w in self.widgets:
                            if w.visible:
                                w.update(dt, self)

                        if self.running:
                            self.force_draw()
                    else:
                        time.sleep(frame_time - dt)
        except Exception as e:
            logger.critical(f"Engine crash: {e}", exc_info=True)
        finally:
            logger.info("--- Shutting down GreeterEngine ---")
            self.running = False
            self.canvas.clear()
            self.canvas.render()

            try:
                self.greetd.close()
            except Exception:
                pass

            self.canvas.exit_alternate_screen()


if __name__ == "__main__":
    app = GreeterEngine(CONFIG)
    app.run()
