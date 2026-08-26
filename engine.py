import collections.abc
import copy
import importlib.util
import logging
import time
from typing import Any, cast

from gleaf import BaseCanvas
from gleaf.backends.base import UNSET
from gleaf.styles import Modifiers
from oakey import Empty, KeyListener, Keys

from audio_manager import AudioManager
from canvas import BACKEND, CANVAS  # noqa: F401
from config import CONFIG
from greetd_ipc import GreetdClient, GreetdError
from parser import parse_expr
from registry import UIRegistry

UIRegistry.set_canvas(CANVAS)

AUDIO_MANAGER = AudioManager()

# ==========================================
# 0. LOGGING SETUP
# ==========================================
logging.basicConfig(
    filename="/tmp/standalone-dm.log",
    filemode="a",
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.DEBUG,
    force=True,
)
logger = logging.getLogger("engine")

# ==========================================
# 1. THE OMNI-CONFIG
# ==========================================

# CONFIG


# ==========================================
# 2. WIDGET BASE CLASS
# ==========================================


class BaseWidget:
    CONFIG = CONFIG
    UIRegistry = UIRegistry

    def __init__(
        self,
        name: str | None,
        x: int | str,
        y: int | str,
        z_index: int | str,
        width: int | str | None = None,
        height: int | str | None = None,
        anchor: str | None = None,
        config: dict | None = None,
    ):
        self.name = name
        self.config = config or {}
        self.x_raw = x
        self.y_raw = y
        self.z_index = z_index
        self.w_raw = width
        self.h_raw = height
        self.anchor = anchor
        self.focusable = False
        self.focused = False
        self.visible = True
        self.value = ""

        if name:
            self.UIRegistry.register(name, self)

    @property
    def w(self):
        return (
            int(
                self.parse(
                    self.w_raw, self.UIRegistry.canvas.width, self.config or self.CONFIG
                )
            )
            if self.w_raw
            else 0
        )

    @property
    def h(self):
        return (
            int(
                self.parse(
                    self.h_raw,
                    self.UIRegistry.canvas.height,
                    self.config or self.CONFIG,
                )
            )
            if self.h_raw
            else 0
        )

    @property
    def anchorx(self):
        return int(
            self.parse(
                self.x_raw, self.UIRegistry.canvas.width, self.config or self.CONFIG
            )
        )

    @property
    def anchory(self):
        return int(
            self.parse(
                self.y_raw, self.UIRegistry.canvas.height, self.config or self.CONFIG
            )
        )

    @property
    def top(self):
        anchor = self.anchor or self.CONFIG["anchors"].get(self.name, "nw")

        match anchor:
            case "nw" | "n" | "ne":
                return self.anchory
            case "w" | "center" | "e":
                return self.anchory - self.h // 2
            case "sw" | "s" | "se":
                return self.anchory - self.h + 1
            case _:
                raise ValueError(
                    f"Invalid Anchor for {type(self).__name__}: {self.name or 'not named'}"
                )

    @property
    def bottom(self):
        anchor = self.anchor or self.CONFIG["anchors"].get(self.name, "nw")

        match anchor:
            case "nw" | "n" | "ne":
                return self.anchory + self.h - 1
            case "w" | "center" | "e":
                return self.anchory + self.h // 2 - 1 + self.h % 2
            case "sw" | "s" | "se":
                return self.anchory
            case _:
                raise ValueError(
                    f"Invalid Anchor for {type(self).__name__}: {self.name or 'not named'}"
                )

    @property
    def left(self):
        anchor = self.anchor or self.CONFIG["anchors"].get(self.name, "nw")

        match anchor:
            case "nw" | "w" | "sw":
                return self.anchorx
            case "n" | "center" | "s":
                return self.anchorx - self.w // 2
            case "ne" | "e" | "se":
                return self.anchorx - self.w + 1
            case _:
                raise ValueError(
                    f"Invalid Anchor for {type(self).__name__}: {self.name or 'not named'}"
                )

    @property
    def right(self):
        anchor = self.anchor or self.CONFIG["anchors"].get(self.name, "nw")

        match anchor:
            case "nw" | "w" | "sw":
                return self.anchorx + self.w - 1
            case "n" | "center" | "s":
                return self.anchorx + self.w // 2 - 1 + self.w % 2
            case "ne" | "e" | "se":
                return self.anchorx
            case _:
                raise ValueError(
                    f"Invalid Anchor for {type(self).__name__}: {self.name or 'not named'}"
                )

    @property
    def centerx(self):
        return self.left + self.w // 2

    @property
    def centery(self):
        return self.top + self.h // 2

    def _get_context_refs(self) -> dict:
        """Collects current state refs available for expression evaluation."""
        return {
            "self": self,
            "canvas_w": UIRegistry.canvas.width,
            "canvas_h": UIRegistry.canvas.height,
            **UIRegistry.widgets,
        }

    def parse(self, expr: Any, length: float | None = None, config=None) -> Any:
        """
        General-purpose child parse method.
        Can return any type (numbers, strings, colors, objects).
        """
        return parse_expr(
            expr,
            length=length,
            config=config or (self.config or self.CONFIG),
            refs=self._get_context_refs(),
        )

    def get_coord(self, expr: Any, length: int | None = None, config=None) -> int:
        """
        Strict layout method. Evaluates an expression and strictly enforces
        an integer output for sizing and positioning coordinates.
        """
        res = self.parse(expr, length=length, config=config)

        if isinstance(res, (int, float)):
            return int(res)

        raise TypeError(
            f"Strict coordinate parsing failed for expression '{expr}': "
            f"Expected numeric result, but got {type(res).__name__} ({res!r})"
        )

    def get_coords(
        self,
        canvas: BaseCanvas,
        width: int | None = None,
        height: int | None = None,
        config=None,
    ) -> tuple[int, int]:
        # div = (
        #     config["engine"]["math_center_divisor"]
        #     if config
        #     else self.config["engine"]["math_center_divisor"]
        # )

        x = self.get_coord(self.x_raw, canvas.width, config)
        y = self.get_coord(self.y_raw, canvas.height, config)

        # x_res = (
        #     (canvas.width // div) - ((width or 0) // div)
        #     if self.x_raw == "center"
        #     else x
        # )
        # y_res = (
        #     (canvas.height // div) - ((height or 0) // div)
        #     if self.y_raw == "center"
        #     else y
        # )
        return x, y

    def update(self, dt: float, engine: "GreeterEngine"):
        pass

    def draw(self, canvas: BaseCanvas, config: dict):
        pass

    def handle_key(self, key: str, engine: "GreeterEngine") -> bool:
        return False

    def on_focus(self, engine):
        pass

    def on_focus_loss(self, engine):
        pass


# ==========================================
# 3. MODULAR DEFAULT WIDGETS
# ==========================================
class DefaultBackground(BaseWidget):
    def __init__(self, config: dict):
        super().__init__(
            "default_bg", 0, 0, config["layout"]["z_background"], "full", "full"
        )

    def draw(self, canvas, config):
        canvas.edit_region_colors(
            0,
            0,
            canvas.width,
            canvas.height,
            None,
            config["theme"]["bg_color"],
        )


class LabelWidget(BaseWidget):
    """Draws a Label"""

    def __init__(
        self,
        name: str | None,
        x: int | str,
        y: int | str,
        z: int,
        text: str,
        fg=UNSET,
        bg=UNSET,
        style=UNSET,
        config: dict | None = None,
    ):
        super().__init__(name, x, y, z, None, 1, config=config)
        self.text = text
        self.fg = fg
        self.bg = bg
        self.style = style

    @property
    def w(self):
        return len(self.text)

    def draw(self, canvas: BaseCanvas, config: dict):
        # c_x, c_y = self.get_coords(canvas, None, None, config)

        canvas.put_str(self.left, self.top, self.text, self.fg, self.bg, self.style)


class BoxBackgroundWidget(BaseWidget):
    """Draws the static box and title."""

    def __init__(self, name, x, y, z, w, h, config: dict):
        super().__init__(name, x, y, z, w, h)

    def draw(self, canvas, config):
        thm = config["theme"]
        # c_x, c_y = self.get_coords(canvas, lyt["box_width"], lyt["box_height"], config)

        canvas.edit_region_colors(
            self.left,
            self.top,
            self.w,
            self.h,
            None,
            thm["box_bg"],
        )

        canvas.put_block(
            self.left, self.top, (" " * self.w + "\n") * self.h, self.w, self.h
        )


class InputWidget(BaseWidget):
    """A highly reusable text input field."""

    def __init__(
        self,
        name: str,
        x,
        y,
        label_active_key: str,
        label_idle_key: str,
        is_password: bool,
        config: dict,
    ):
        super().__init__(name, x, y, config["layout"]["z_ui_elements"])
        self.focusable = True
        self.is_password = is_password
        self.label_active_key = label_active_key
        self.label_idle_key = label_idle_key

    def handle_key(self, key: str, engine) -> bool:
        if key == Keys.BACKSPACE:
            self.value = self.value[:-1]
            return True
        elif len(key) == 1 and key.isprintable():
            self.value += key
            # Clear auth messages on new typing
            auth_logic = cast(AuthLogicWidget, engine.get_widget("auth_logic"))
            if auth_logic:
                auth_logic.sys_msg = engine.config["system"]["empty_string"]
            return True
        return False

    def draw(self, canvas, config):
        lyt, txt, thm = config["layout"], config["text"], config["theme"]
        # c_x, c_y = self.get_coords(canvas, lyt["box_width"], lyt["box_height"], config)

        lbl = txt[self.label_active_key] if self.focused else txt[self.label_idle_key]
        col = thm["text_accent"] if self.focused else thm["text_main"]
        disp_val = (
            (txt["mask_char"] * len(self.value)) if self.is_password else self.value
        )

        canvas.put_str(
            self.left,
            self.top,
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
            config["layout"]["msg_x"],
            config["layout"]["msg_y"],
            config["layout"]["z_ui_elements"],
        )

        self.sys_msg = config["system"]["empty_string"]
        self.msg_is_error = False

    def draw(self, canvas, config):
        if not self.sys_msg:
            return

        lyt, thm = (
            config["layout"],
            config["theme"],
        )

        c_x, c_y = self.get_coords(
            canvas,
            lyt["box_width"],
            lyt["box_height"],
            config,
        )

        m_col = thm["text_error"] if self.msg_is_error else thm["text_success"]

        canvas.put_str(
            self.left,
            self.top,
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

        txt = engine.config["text"]
        sys_cfg = engine.config["system"]

        username = w_user.value
        password = w_pass.value

        self.sys_msg = txt["msg_authenticating"]
        self.msg_is_error = False

        engine.force_draw()

        logger.info(f"Attempting login for user: {username}")

        try:
            # ----------------------------------------------------------
            # IMPORTANT:
            #
            # Cancel the previous session BEFORE create_session().
            #
            # This is what nwg-hello does. It is necessary because after
            # auth_error the previous session remains configured from
            # the greeter's point of view.
            #
            # On the first login there may be nothing to cancel, so
            # failure is intentionally ignored.
            # ----------------------------------------------------------

            try:
                engine.greetd.cancel_session()
            except Exception as e:
                logger.debug(f"No previous greetd session to cancel: {e}")

            # ----------------------------------------------------------
            # Start a fresh authentication session.
            # ----------------------------------------------------------

            resp = engine.greetd.create_session(username)

            # ----------------------------------------------------------
            # PAM authentication conversation.
            # ----------------------------------------------------------

            while resp.get("type") == "auth_message":
                msg_type = resp.get(
                    "auth_message_type",
                    "visible",
                )

                msg = resp.get(
                    "auth_message",
                    "",
                )

                logger.debug(f"greetd auth message: type={msg_type!r}, message={msg!r}")

                if msg_type == "secret":
                    response = password

                elif msg_type == "visible":
                    response = username

                elif msg_type in ("info", "error"):
                    response = None

                else:
                    logger.error(
                        f"Unknown greetd authentication message type: {msg_type!r}"
                    )

                    self._fail(
                        txt["msg_fail"],
                        w_pass,
                        engine,
                    )

                    return

                resp = engine.greetd.post_auth_message_response(response)

            # ----------------------------------------------------------
            # WRONG PASSWORD
            # ----------------------------------------------------------

            if resp.get("type") == "error" and resp.get("error_type") == "auth_error":
                description = resp.get(
                    "description",
                    txt["msg_fail"],
                )

                logger.warning(f"Authentication failed for {username}: {description}")

                # IMPORTANT:
                #
                # Do NOT call cancel_session() here.
                #
                # The next attempt will perform the cancellation
                # BEFORE create_session(), exactly like nwg-hello.
                self._fail(
                    txt["msg_fail"],
                    w_pass,
                    engine,
                )

                return

            # ----------------------------------------------------------
            # SUCCESS
            # ----------------------------------------------------------

            if resp.get("type") == "success":
                logger.info(
                    f"Authentication successful for {username}. Starting session..."
                )

                self.sys_msg = txt["msg_success"]
                self.msg_is_error = False

                engine.force_draw()

                engine.greetd.start_session(
                    cmd=sys_cfg["default_session_cmd"],
                    env=sys_cfg.get("env"),
                )

                engine.running = False

                return

            # ----------------------------------------------------------
            # Unexpected response.
            # ----------------------------------------------------------

            logger.error(f"Unexpected response from greetd: {resp!r}")

            self._fail(
                txt["msg_fail"],
                w_pass,
                engine,
            )

        except GreetdError as e:
            logger.error(f"Greetd exception during login: {e.description}")

            self._fail(
                e.description,
                w_pass,
                engine,
            )

        except (ConnectionError, OSError) as e:
            logger.error(f"Greetd IPC connection error during login: {e}")

            self._fail(
                txt["msg_fail"],
                w_pass,
                engine,
            )

    def _fail(
        self,
        msg: str,
        pass_widget,
        engine,
    ):
        """
        Handle an authentication failure.

        This intentionally does NOT communicate with greetd.

        The stale session is cancelled at the beginning of the NEXT
        attempt_login(), before create_session().
        """

        self.sys_msg = msg
        self.msg_is_error = True

        pass_widget.value = engine.config["system"]["empty_string"]

        engine.force_draw()


# ==========================================
# 4. THE CORE ENGINE
# ==========================================


def deep_update(d, u):
    """Recursively deep updates dictionary d with dictionary u."""
    for k, v in u.items():
        if isinstance(v, collections.abc.Mapping):
            d[k] = deep_update(d.get(k, {}), v)
        else:
            d[k] = v
    return d


class GreeterEngine:
    def __init__(self, config: dict):
        self.original_config = copy.deepcopy(config)
        self.config = config
        self.loaded_plugins = []

        self._load_plugin_modules()

        self.canvas = CANVAS
        self.audio_manager = AUDIO_MANAGER
        self.greetd = GreetdClient()
        self.widgets: list[BaseWidget] = []
        self.running = True

        self.keylistener = None

        self._build_default_widgets()

    def _build_default_widgets(self):

        self.add_widget(DefaultBackground(self.config))
        self.add_widget(
            BoxBackgroundWidget(
                "box_bg",
                self.config["layout"]["box_x"],
                self.config["layout"]["box_y"],
                self.config["layout"]["z_ui_base"],
                self.config["layout"]["box_width"],
                self.config["layout"]["box_height"],
                config=self.config,
            )
        )
        self.add_widget(
            InputWidget(
                "input_user",
                self.config["layout"]["user_x"],
                self.config["layout"]["user_y"],
                "user_active",
                "user_idle",
                False,
                self.config,
            )
        )
        self.add_widget(
            InputWidget(
                "input_pass",
                self.config["layout"]["pass_x"],
                self.config["layout"]["pass_y"],
                "pass_active",
                "pass_idle",
                True,
                self.config,
            )
        )
        self.add_widget(AuthLogicWidget(self.config))

        self.add_widget(
            LabelWidget(
                "title",
                self.config["layout"]["title_x"],
                self.config["layout"]["title_y"],
                self.config["layout"]["z_ui_elements"],
                self.config["text"]["title"],
                self.config["theme"]["text_main"],
                style=Modifiers.BOLD,
                config=self.config,
            )
        )

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
            focusables[current_idx].on_focus_loss(self)

        next_idx = (
            (current_idx - 1) % len(focusables)
            if reverse
            else (current_idx + 1) % len(focusables)
        )
        focusables[next_idx].focused = True
        focusables[next_idx].on_focus(self)

    def _load_plugin_modules(self):
        """Imports modules, runs config(), and handles dynamic plugin list changes."""
        max_passes = 3
        current_pass = 0

        # Keep a cumulative list of overrides harvested across all passes
        # so they can re-assert themselves if we have to wipe the config.
        all_discovered_overrides = []

        while current_pass < max_passes:
            current_pass += 1
            expected_plugins = list(self.config["engine"]["plugins"])
            self.loaded_plugins.clear()

            for plugin_name in expected_plugins:
                try:
                    logger.info(
                        f"Importing plugin module: {plugin_name} (Pass {current_pass})"
                    )
                    spec = importlib.util.spec_from_file_location(
                        plugin_name, f"/usr/share/log/plugins/{plugin_name}.py"
                    )
                    if spec and spec.loader:
                        plugin_module = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(plugin_module)

                        if hasattr(plugin_module, "config"):
                            logger.debug(f"Triggering config() hook for {plugin_name}")
                            plugin_module.config(self.config)

                        self.loaded_plugins.append((plugin_name, plugin_module))
                except Exception as e:
                    logger.error(
                        f"Failed to load plugin [{plugin_name}]: {e}", exc_info=True
                    )

            # Harvest any new overrides injected by plugins during this pass
            if "__overrides" in self.config:
                all_discovered_overrides.extend(self.config.pop("__overrides"))

            # Sequentially deep-merge ALL accumulated overrides
            for override_dict in all_discovered_overrides:
                if isinstance(override_dict, dict):
                    deep_update(self.config, override_dict)

            # --- THE LOOP BREAK ---
            # Check if the user config altered the plugin list!
            new_plugins = self.config["engine"]["plugins"]
            if new_plugins != expected_plugins:
                logger.info(
                    f"Plugin list altered by config: {expected_plugins} -> {new_plugins}"
                )

                # 1. Wipe the working config to remove "ghost state" from discarded plugins
                self.config = copy.deepcopy(self.original_config)

                # 2. Force the pristine config to use the newly requested plugin list
                self.config["engine"]["plugins"] = new_plugins

                # Loop again to load the new plugins!
                # (The user overrides are safe in all_discovered_overrides and will be reapplied)
                continue

            # If we reach here, the plugin list has stabilized
            break

        if current_pass >= max_passes:
            logger.warning("Max plugin reload passes reached! Infinite loop prevented.")

    def _setup_plugins(self):
        """Runs the setup() hooks for already imported modules."""
        for plugin_name, plugin_module in self.loaded_plugins:
            try:
                # PHASE 2 Hook
                if hasattr(plugin_module, "setup"):
                    logger.info(f"Triggering setup() hook for {plugin_name}")
                    plugin_module.setup(self)
            except Exception as e:
                logger.error(f"Plugin setup error [{plugin_name}]: {e}", exc_info=True)

    def reload_plugins(self, new_plugins_list: list[str] | None = None):
        """Completely resets engine state and hot-reloads the UI."""
        logger.info("--- HOT RELOADING PLUGINS ---")

        if new_plugins_list is not None:
            self.original_config["engine"]["plugins"] = new_plugins_list

        # Revert to pristine snapshot (this preserves __active_user_idx)
        self.config = copy.deepcopy(self.original_config)
        self.loaded_plugins.clear()

        # Re-run full UI lifecycle
        self._load_plugin_modules()
        self._build_default_widgets()
        self._setup_plugins()

        # Redraw screen instantly
        self.force_draw()
        logger.info("--- HOT RELOAD COMPLETE ---")

    def _process_keys(self, listener: KeyListener, config):
        while not listener.empty():
            try:
                key = listener.get(
                    block=False, timeout=config["engine"]["input_timeout"]
                )
            except Empty:
                key = None

            if key:
                if key == Keys.CTRL_R:
                    self.reload_plugins()
                    break

                elif key == Keys.ESCAPE:
                    logger.info("ESCAPE pressed, shutting down.")
                    self.running = False
                    break

                elif key == Keys.TAB:
                    self._cycle_focus(reverse=False)
                elif key == Keys.SHIFT_TAB:
                    self._cycle_focus(reverse=True)
                elif key == Keys.ENTER:
                    auth = cast(AuthLogicWidget, self.get_widget("auth_logic"))
                    if auth:
                        auth.attempt_login(self)
                else:
                    for w in reversed(self.widgets):
                        if w.focused and w.handle_key(key, self):
                            break

    def auto_resize(self):
        self.canvas.auto_resize()

    def run(self):
        logger.info("--- Starting GreeterEngine ---")

        # 1. FIX GHOST FRAME: Enter alternate screen BEFORE plugins run setup routines!
        self.canvas.enter_alternate_screen()
        self._setup_plugins()

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
                self.keylistener = listener
                while self.running:
                    current_time = time.time()
                    dt = current_time - last_time

                    if dt >= frame_time:
                        last_time = current_time

                        self._process_keys(listener, self.config)

                        for w in self.widgets:
                            if w.visible:
                                w.update(dt, self)

                        if self.running:
                            self.auto_resize()
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
