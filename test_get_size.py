import json
import os
import shutil
import subprocess


def get_allocated_size() -> tuple[int, int]:
    """
    Detects the physical pixel allocation of the current active window
    across Hyprland, Sway, i3, X11 WMs (via xdotool/xwininfo), Cage/Wayland,
    and general screen/terminal fallbacks.
    """

    # 1. Hyprland (Wayland)
    if shutil.which("hyprctl"):
        try:
            res = subprocess.run(
                ["hyprctl", "-j", "activewindow"],
                capture_output=True,
                text=True,
                check=True,
            )
            data = json.loads(res.stdout)
            size = data.get("size")
            if size and len(size) == 2:
                print("Detected via: Hyprland (hyprctl)")
                return int(size[0]), int(size[1])
        except Exception:
            pass

    # 2. Sway or i3 (Wayland / X11 Tiling WMs via IPC tree traversal)
    for cmd in ["swaymsg", "i3-msg"]:
        if shutil.which(cmd):
            try:
                res = subprocess.run(
                    [cmd, "-t", "get_tree"], capture_output=True, text=True, check=True
                )
                data = json.loads(res.stdout)

                def find_focused_rect(node):
                    if node.get("focused") and "rect" in node:
                        return node["rect"]
                    for child in node.get("nodes", []) + node.get("floating_nodes", []):
                        rect = find_focused_rect(child)
                        if rect:
                            return rect
                    return None

                rect = find_focused_rect(data)
                if rect:
                    print(f"Detected via: {cmd.upper()} IPC tree")
                    return int(rect.get("width", 0)), int(rect.get("height", 0))
            except Exception:
                pass

    # 3. Generic X11 (GNOME, KDE/KWin, XFWM, Openbox) via xdotool & xwininfo
    if shutil.which("xdotool") and shutil.which("xwininfo"):
        try:
            win_id = subprocess.run(
                ["xdotool", "getactivewindow"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            if win_id:
                res = subprocess.run(
                    ["xwininfo", "-id", win_id],
                    capture_output=True,
                    text=True,
                    check=True,
                ).stdout
                w, h = 0, 0
                for line in res.splitlines():
                    if "Width:" in line:
                        w = int(line.split(":")[1].strip())
                    elif "Height:" in line:
                        h = int(line.split(":")[1].strip())
                if w > 0 and h > 0:
                    print("Detected via: X11 Window Utilities (xdotool/xwininfo)")
                    return w, h
        except Exception:
            pass

    # 4. Cage (Kiosk) / Pure Wayland Screen Bounds Fallback
    if "WAYLAND_DISPLAY" in os.environ or "DISPLAY" in os.environ:
        try:
            import tkinter as tk

            root = tk.Tk()
            root.withdraw()
            w, h = root.winfo_screenwidth(), root.winfo_screenheight()
            root.destroy()
            if w > 0 and h > 0:
                print("Detected via: Wayland / Cage Screen Allocation Bounds")
                return w, h
        except Exception:
            pass

    # 5. Last Resort: Terminal Character Cell Multipliers
    try:
        size = os.get_terminal_size()
        print("Detected via: Terminal Grid Estimation Fallback")
        return size.columns * 10, size.lines * 20
    except Exception:
        return 800, 600


if __name__ == "__main__":
    w, h = get_allocated_size()
    print(f"Final Allocated Window Size: {w}px x {h}px")
