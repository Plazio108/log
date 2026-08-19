import argparse
import concurrent.futures
import os
import struct

import cv2
import lz4.block
import numpy as np
from PIL import Image

try:
    from tqdm import tqdm
except ImportError:

    def tqdm(iterable, **kwargs):
        return iterable


# Matches the memory layout of TerminalTexture exactly (21 bytes per cell)
TEXTURE_DTYPE = np.dtype(
    [
        ("char", "u4"),
        ("fg_r", "u1"),
        ("fg_g", "u1"),
        ("fg_b", "u1"),
        ("fg_mode", "u1"),
        ("bg_r", "u1"),
        ("bg_g", "u1"),
        ("bg_b", "u1"),
        ("bg_mode", "u1"),
        ("ul_r", "u1"),
        ("ul_g", "u1"),
        ("ul_b", "u1"),
        ("ul_mode", "u1"),
        ("style", "u4"),
        ("style_mode", "u1"),
        ("pad", "u1", 3),
    ]
)


def process_frame(args):
    frame_rgb, out_width, out_height = args

    img = Image.fromarray(frame_rgb).convert("RGBA")

    # Resize to exact terminal character dimensions
    img = img.resize((out_width, out_height * 2), Image.Resampling.LANCZOS)
    arr = np.array(img, dtype=np.uint8)

    top = arr[0::2, :, :]
    bot = arr[1::2, :, :]

    # Initialize a completely blank/transparent texture buffer
    tex = np.zeros((out_height, out_width), dtype=TEXTURE_DTYPE)

    a1 = top[:, :, 3]
    a2 = bot[:, :, 3]

    # Create boolean masks for vectorization
    mask_top = (a1 >= 128) & (a2 < 128)
    mask_bot = (a1 < 128) & (a2 >= 128)
    mask_both = (a1 >= 128) & (a2 >= 128)

    # Mode Constants: 1 = SET

    # --- Top Visible Only ---
    tex["char"][mask_top] = 0x2580
    tex["fg_r"][mask_top] = top[mask_top, 0]
    tex["fg_g"][mask_top] = top[mask_top, 1]
    tex["fg_b"][mask_top] = top[mask_top, 2]
    tex["fg_mode"][mask_top] = 1

    # --- Bottom Visible Only ---
    tex["char"][mask_bot] = 0x2584
    tex["fg_r"][mask_bot] = bot[mask_bot, 0]
    tex["fg_g"][mask_bot] = bot[mask_bot, 1]
    tex["fg_b"][mask_bot] = bot[mask_bot, 2]
    tex["fg_mode"][mask_bot] = 1

    # --- Both Visible ---
    tex["char"][mask_both] = 0x2580

    # Foreground (Top color)
    tex["fg_r"][mask_both] = top[mask_both, 0]
    tex["fg_g"][mask_both] = top[mask_both, 1]
    tex["fg_b"][mask_both] = top[mask_both, 2]
    tex["fg_mode"][mask_both] = 1

    # Background (Bottom color)
    tex["bg_r"][mask_both] = bot[mask_both, 0]
    tex["bg_g"][mask_both] = bot[mask_both, 1]
    tex["bg_b"][mask_both] = bot[mask_both, 2]
    tex["bg_mode"][mask_both] = 1

    # Get raw struct bytes and compress
    raw_bytes = tex.tobytes()
    compressed = lz4.block.compress(raw_bytes, store_size=False)

    # Return Frame Size (UInt32) + LZ4 Compressed Data
    return struct.pack(">I", len(compressed)) + compressed


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

    ret, first_frame = cap.read()
    if not ret:
        return

    h_orig, w_orig, _ = first_frame.shape
    if height is None:
        aspect = h_orig / w_orig
        height = max(1, int(width * aspect * 0.5))

    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

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

    # Header: Magic(4s), Width(H), Height(H), Frames(I), Duration(f) = 16 bytes
    header = struct.pack(
        ">4sHHIf", b"SPRT", width, height, total_frames, float(duration)
    )

    tasks = [(f, width, height) for f in raw_frames]

    with open(output_path, "wb") as out_file:
        out_file.write(header)

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
