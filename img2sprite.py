import json
from PIL import Image
import sys

def convert_image_to_sprite(image_path: str, out_width: int):
    img = Image.open(image_path).convert("RGBA")
    
    # Calculate aspect ratio (terminal fonts are usually ~2x as tall as they are wide)
    w, h = img.size
    aspect = h / w
    out_height = int(out_width * aspect * 0.5) 
    
    # Resize to exact terminal character dimensions
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
                # Fully transparent cell (keeps whatever is behind it in the UI)
                row.append({"char": None, "fg": None, "bg": None, "style": None})
            elif a1 >= 128 and a2 < 128:
                # Top visible, bottom transparent
                row.append({"char": "▀", "fg": (r1, g1, b1), "bg": None, "style": 0})
            elif a1 < 128 and a2 >= 128:
                # Bottom visible, top transparent
                row.append({"char": "▄", "fg": (r2, g2, b2), "bg": None, "style": 0})
            else:
                # Both visible
                row.append({"char": "▀", "fg": (r1, g1, b1), "bg": (r2, g2, b2), "style": 0})
        matrix.append(row)
        
    return matrix

if __name__ == "__main__":
    # Usage: python img2sprite.py avatar.png 20 > avatar.json
    sprite_data = convert_image_to_sprite(sys.argv[1], int(sys.argv[2]))
    print(json.dumps(sprite_data))
