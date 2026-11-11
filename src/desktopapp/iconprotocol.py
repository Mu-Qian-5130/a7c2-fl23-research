"""Bounded portable artwork for the fixed camera command, without device offsets."""
import hashlib
import struct

MAGIC = b'A7ICLOOK'
MASK_BYTES = 26 * 19 + 22 * 16
MAX_PACKET = 16 + 3423 + MASK_BYTES + 32


def pack(color, icon):
    from PIL import Image
    from looktool import iconfile
    if len(color) not in (1324, 3423):
        raise ValueError('Unsupported color packet')
    large = iconfile.mask(icon)
    small = Image.frombytes('L', iconfile.SIZE, large).resize((22, 16), Image.Resampling.LANCZOS).tobytes()
    body = MAGIC + struct.pack('<II', len(color), MASK_BYTES) + color + large + small
    return body + hashlib.sha256(body).digest()


def unpack(packet):
    if not isinstance(packet, bytes) or not 16 + 1324 + MASK_BYTES + 32 <= len(packet) <= MAX_PACKET:
        raise ValueError('Artwork packet size differs')
    color_size, mask_size = struct.unpack_from('<II', packet, 8)
    if (packet[:8] != MAGIC or color_size not in (1324, 3423) or mask_size != MASK_BYTES
            or len(packet) != 16 + color_size + mask_size + 32
            or hashlib.sha256(packet[:-32]).digest() != packet[-32:]):
        raise ValueError('Artwork packet integrity differs')
    masks = packet[16 + color_size:-32]
    if not any(masks[:494]) or not any(masks[494:]):
        raise ValueError('Artwork mask is empty')
    return packet[16:16 + color_size], masks
