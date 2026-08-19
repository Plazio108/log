import argparse
import json

import cv2
from PIL import Image


def convert_frame_to_sprite(
    img: Image.Image, out_width: int, out_height: int | None = None
) -> list[list[dict]]:
    """Converts a PIL Image into a terminal sprite matrix using half-blocks (▀ / ▄).

    If out_height is not provided, it is automatically calculated using the image's
    aspect ratio, adjusted for standard ~2:1 terminal cell proportions.
    """
    img = img.convert("RGBA")
    w, h = img.size

    if out_height is None:
        aspect = h / w
        out_height = max(1, int(out_width * aspect * 0.5))

    # Resize to character width and 2x character height (1 char cell = 2 vertical pixels)
    img = img.resize((out_width, out_height * 2), Image.Resampling.LANCZOS)

    matrix = []
    for y in range(out_height):
        row = []
        for x in range(out_width):
            # Top pixel (Foreground)
            r1, g1, b1, a1 = img.getpixel((x, y * 2))
            # Bottom pixel (Background)
            r2, g2, b2, a2 = img.getpixel((x, y * 2 + 1))

            # Transparency Logic
            if a1 < 128 and a2 < 128:
                row.append({"char": None, "fg": None, "bg": None, "style": None})
            elif a1 >= 128 and a2 < 128:
                row.append({"char": "▀", "fg": [r1, g1, b1], "bg": None, "style": 0})
            elif a1 < 128 and a2 >= 128:
                row.append({"char": "▄", "fg": [r2, g2, b2], "bg": None, "style": 0})
            else:
                row.append(
                    {
                        "char": "▀",
                        "fg": [r1, g1, b1],
                        "bg": [r2, g2, b2],
                        "style": 0,
                    }
                )
        matrix.append(row)

    return matrix


def convert_video_to_sprite_json(
    video_path: str,
    output_json_path: str,
    width: int,
    height: int | None = None,
    frame_delay: float | None = None,
    target_fps: float | None = None,
    loop: bool = True,
):
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise FileNotFoundError(f"Failed to open video file: {video_path}")

    native_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0

    # Determine frame duration and downsampling step
    if frame_delay is not None:
        duration = round(float(frame_delay), 4)
        frame_step = 1
    elif target_fps is not None and target_fps > 0:
        duration = round(1.0 / target_fps, 4)
        frame_step = max(1, int(round(native_fps / target_fps)))
    else:
        duration = round(1.0 / native_fps, 4)
        frame_step = 1

    frames = []
    raw_frame_idx = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if raw_frame_idx % frame_step == 0:
            # Convert OpenCV BGR array to RGBA PIL Image
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGBA)
            pil_img = Image.fromarray(frame_rgb)

            matrix = convert_frame_to_sprite(
                pil_img, out_width=width, out_height=height
            )
            frames.append({"duration": duration, "matrix": matrix})

        raw_frame_idx += 1

    cap.release()

    animation_payload = {"loop": loop, "frames": frames}

    with open(output_json_path, "w", encoding="utf-8") as f:
        json.dump(animation_payload, f, indent=2)

    actual_h = len(frames[0]["matrix"]) if frames else 0
    print(
        f"Exported {len(frames)} frames ({width}x{actual_h}) to '{output_json_path}' "
        f"with frame duration {duration}s."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Convert MP4 video to Terminal Sprite JSON."
    )
    parser.add_argument(
        "-i", "--input", required=True, help="Input video path (MP4/GIF)"
    )
    parser.add_argument("-o", "--output", required=True, help="Output JSON path")
    parser.add_argument(
        "-w", "--width", type=int, default=32, help="Terminal grid width in characters"
    )
    parser.add_argument(
        "-H",
        "--height",
        type=int,
        default=None,
        help="Terminal grid height in lines (optional, auto-calculated if omitted)",
    )
    parser.add_argument(
        "-d",
        "--delay",
        type=float,
        default=None,
        help="Custom duration per frame in seconds (e.g. 0.05 for 50ms)",
    )
    parser.add_argument(
        "--fps",
        type=float,
        default=None,
        help="Target FPS to sample video frames (e.g. 15)",
    )
    parser.add_argument(
        "--no-loop", action="store_false", dest="loop", help="Disable looping flag"
    )

    args = parser.parse_args()

    convert_video_to_sprite_json(
        video_path=args.input,
        output_json_path=args.output,
        width=args.width,
        height=args.height,
        frame_delay=args.delay,
        target_fps=args.fps,
        loop=args.loop,
    )
