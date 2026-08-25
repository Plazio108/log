import subprocess


def change_kitty_font_size(size_change: str | float) -> None:
    """
    Adjusts Kitty font size.
    - Relative changes: "+2.0" (zoom in), "-2.0" (zoom out)
    - Absolute size: 14.0
    - Reset to default: 0
    """
    subprocess.run(
        [
            "kitty",
            "@",
            "set-font-size",
            "--",  # Stops CLI option parsing so negative values aren't read as flags
            str(size_change),
        ],
        check=True,
    )


# Both incrementing and decrementing will now work:
change_kitty_font_size("+2.0")
change_kitty_font_size("-2.0")
