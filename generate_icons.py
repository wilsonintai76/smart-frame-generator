"""generate_icons.py — Resize generated concept images to Fusion 360 icon sizes.

Fusion 360 command icons must be PNG files named:
  16x16.png, 32x32.png, 64x64.png
placed in the command's resources/ folder.

Run this script once from the add-in root directory.
Requires Pillow (pip install pillow).
"""

import os
import shutil
import struct
import zlib

ADDIN_ROOT = os.path.dirname(os.path.abspath(__file__))

ICON_SOURCES = {
    'FrameGeneratorCommand': os.path.join(
        r'C:\Users\wilson\.gemini\antigravity-ide\brain\0e7bd247-8e25-4210-a8ce-ca222a72d957',
        'icon_generate_frame_1782872532442.png'
    ),
    'FrameJointCommand': os.path.join(
        r'C:\Users\wilson\.gemini\antigravity-ide\brain\0e7bd247-8e25-4210-a8ce-ca222a72d957',
        'icon_apply_joint_1782872541143.png'
    ),
}

SIZES = [16, 32, 64]


def resize_with_pillow(src_path, dst_path, size):
    from PIL import Image
    img = Image.open(src_path).convert('RGBA')
    img = img.resize((size, size), Image.LANCZOS)
    img.save(dst_path, 'PNG')


def make_solid_png(dst_path, size, r, g, b):
    """Fallback: create a solid-colour PNG if Pillow is unavailable."""
    def chunk(name, data):
        c = name + data
        return struct.pack('>I', len(data)) + c + struct.pack('>I', zlib.crc32(c) & 0xffffffff)

    raw = b''
    for _ in range(size):
        row = b'\x00'  # filter type None
        for _ in range(size):
            row += bytes([r, g, b, 255])
        raw += row

    compressed = zlib.compress(raw)
    sig   = b'\x89PNG\r\n\x1a\n'
    ihdr  = chunk(b'IHDR', struct.pack('>IIBBBBB', size, size, 8, 6, 0, 0, 0))
    idat  = chunk(b'IDAT', compressed)
    iend  = chunk(b'IEND', b'')
    with open(dst_path, 'wb') as f:
        f.write(sig + ihdr + idat + iend)


for cmd_name, src_path in ICON_SOURCES.items():
    resources_dir = os.path.join(ADDIN_ROOT, 'commands', cmd_name, 'resources')
    os.makedirs(resources_dir, exist_ok=True)

    for size in SIZES:
        dst = os.path.join(resources_dir, f'{size}x{size}.png')
        try:
            resize_with_pillow(src_path, dst, size)
            print(f'  ✓  {cmd_name}/{size}x{size}.png  (Pillow)')
        except ImportError:
            # Pillow not available — use solid colour fallback
            if 'Generator' in cmd_name:
                make_solid_png(dst, size, 74, 158, 204)   # Steel blue
            else:
                make_solid_png(dst, size, 230, 126, 34)   # Orange
            print(f'  ✓  {cmd_name}/{size}x{size}.png  (solid fallback)')
        except FileNotFoundError:
            if 'Generator' in cmd_name:
                make_solid_png(dst, size, 74, 158, 204)
            else:
                make_solid_png(dst, size, 230, 126, 34)
            print(f'  ✓  {cmd_name}/{size}x{size}.png  (source missing — solid fallback)')

print('\nDone.')
