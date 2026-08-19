import argparse
import concurrent.futures
import os
import struct

import cv2
import numpy as np
from PIL import Image

try:
    from tqdm import tqdm
except ImportError:

    def tqdm(iterable, **kwargs):
        return iterable


def process_frame(args):
    frame_rgb, out_width, out_height = args

    img = Image.fromarray(frame_rgb).convert("RGBA")
    w, h = img.size

    # Resize to exact terminal character dimensions
    img = img.resize((out_width, out_height * 2), Image.Resampling.LANCZOS)
    arr = np.array(img, dtype=np.uint8)

    top = arr[0::2, :, :]
    bot = arr[1::2, :, :]

    frame_bytes = bytearray()

    for y in range(out_height):
        for x in range(out_width):
            r1, g1, b1, a1 = top[y, x]
            r2, g2, b2, a2 = bot[y, x]

            # Binary Encoding Flags:
            # 0 = Fully transparent
            # 1 = FG visible only
            # 3 = Both FG and BG visible

            if a1 < 128 and a2 < 128:
                # Transparent
                frame_bytes.extend(struct.pack(">IBBBBBBB", 0, 0, 0, 0, 0, 0, 0, 0))
            elif a1 >= 128 and a2 < 128:
                # Top visible (▀ = 0x2580)
                frame_bytes.extend(
                    struct.pack(">IBBBBBBB", 0x2580, r1, g1, b1, 0, 0, 0, 1)
                )
            elif a1 < 128 and a2 >= 128:
                # Bottom visible (▄ = 0x2584)
                frame_bytes.extend(
                    struct.pack(">IBBBBBBB", 0x2584, r2, g2, b2, 0, 0, 0, 1)
                )
            else:
                # Both visible (▀ = 0x2580)
                frame_bytes.extend(
                    struct.pack(">IBBBBBBB", 0x2580, r1, g1, b1, r2, g2, b2, 3)
                )

    return frame_bytes


def convert_to_bin(
    video_path: str, output_path: str, width: int, height: int | None, fps: float | None
):
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise FileNotFoundError(f"Cannot open {video_path}")

    native_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0

    if fps and fps > 0:
        duration = 1.0 / fps
        frame_step = max(1, int(round(native_fps / fps)))
    else:
        duration = 1.0 / native_fps
        frame_step = 1

    print("Extracting frames...")
    raw_frames = []
    raw_idx = 0

    # Auto-calculate height based on first frame if not provided
    ret, first_frame = cap.read()
    if not ret:
        return

    h_orig, w_orig, _ = first_frame.shape
    if height is None:
        aspect = h_orig / w_orig
        height = max(1, int(width * aspect * 0.5))

    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)  # Reset

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if raw_idx % frame_step == 0:
            raw_frames.append(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        raw_idx += 1
    cap.release()

    total_frames = len(raw_frames)
    print(f"Packing {total_frames} frames into binary at {width}x{height}...")

    # Magic(4s), Width(H), Height(H), Frames(I), Duration(f) = 16 bytes
    header = struct.pack(
        ">4sHHIf", b"SPRT", width, height, total_frames, float(duration)
    )

    tasks = [(f, width, height) for f in raw_frames]

    with open(output_path, "wb") as out_file:
        out_file.write(header)

        # Parallelize the packing math
        with concurrent.futures.ProcessPoolExecutor() as executor:
            results = list(tqdm(executor.map(process_frame, tasks), total=total_frames))

            out_file.writelines(results)

    mb_size = os.path.getsize(output_path) / (1024 * 1024)
    print(f"Done! Exported {output_path} ({mb_size:.2f} MB)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-i", "--input", required=True)
    parser.add_argument("-o", "--output", required=True)
    parser.add_argument("-w", "--width", type=int, default=100)
    parser.add_argument("-H", "--height", type=int, default=None)
    parser.add_argument("--fps", type=float, default=None)

    args = parser.parse_args()
    convert_to_bin(args.input, args.output, args.width, args.height, args.fps)
