"""Pip's screenshot-matched pixel artwork and time-based desktop animation.

The canvas keeps its items between frames, so animation never destroys hit
targets. All coordinates are logical pixels; Tk applies the monitor's DPI.
"""
import math
import struct
import tkinter as tk
import zlib

from pip_pixels import WIDTH, HEIGHT, PIXELS


def smoothstep(value):
    value = min(1.0, max(0.0, value))
    return value * value * (3 - 2 * value)


def pet_pose(frame, activity="idle"):
    """Sample a pose at a fractional legacy 60ms frame, without quantization."""
    t = frame * .06
    phase = t * 2 * math.pi / 3.8
    greeting = t % 14.4
    wave = (smoothstep((greeting - 12.0) / .4) *
            smoothstep((14.4 - greeting) / .5)) if activity == "idle" else 0.0
    if activity == "happy":
        wave = 1.0
    working = activity == "working"
    carried = activity == "dragging"
    happy = activity == "happy"
    pose = {
        "bob": math.sin(phase) * 1.8,
        "lean": math.sin(phase * .5) * .65,
        "arm": math.sin(t * 7.5) * (2.2 if working else 1.3),
        "wave": wave,
        "blink": max(0.0, 1 - abs(t % 4.9 - 4.5) / .11),
        "look": 2.0 if activity == "thinking" else math.sin(t * .6) * .8,
        "hop": -2.6 * (1 - math.cos(t * 2 * math.pi / 1.3)) if happy else 0.0,
        "feet": math.sin(t * 4.0 + .5) * (1.3 if working or carried else .25),
        "breath": math.sin(phase - .6) * .012,
        "tilt": -3.0 if activity == "thinking" else math.sin(phase * .5) * 1.1,
        "left_arm": 14.0 if carried else (4.0 if working else 0.0),
        "right_arm": -28 * wave - (12 if carried else 0),
        "smile": float(happy),
        "concern": float(activity == "error"),
    }
    return {key: 0.0 for key in pose} if activity == "reference" else pose


def claude_pixel(red, green, blue):
    """Claude palette swap, keeping the reference's per-pixel shade variation."""
    if max(red, green, blue) - min(red, green, blue) <= 10:
        return red, green, blue  # the original dark outline
    if green > red * 1.15 and abs(blue-green) < 40:
        light = max(red, green, blue) / 255
        return tuple(round(c * light) for c in (255, 244, 230))
    # Reference's main blue (131,158,243) becomes Claude #d97757.
    bright = (blue * 217/243, green * 119/158, red * 87/131)
    dark = (blue * .60, green * .80, red * .80)
    mix = smoothstep((blue - 110) / 45)
    return tuple(min(255, max(0, round(a + (b-a)*mix))) for a,b in zip(dark,bright))


def sprite_rgba():
    """Return the same pixel geometry as the reference, in Claude colors."""
    out = bytearray(PIXELS)
    for i in range(0, len(out), 4):
        if out[i+3]:
            out[i:i+3] = bytes(claude_pixel(*out[i:i+3]))
    return bytes(out)


def sprite_png(scale=1.0):
    """Build a DPI-sized PNG with nearest-neighbor pixels, using only stdlib."""
    return rgba_png(sprite_rgba(), scale)


def rgba_png(pixels, scale=1.0):
    w, h = max(1, round(WIDTH*scale)), max(1, round(HEIGHT*scale))
    rows = bytearray()
    for y in range(h):
        rows.append(0)  # PNG filter: none
        sy = min(HEIGHT-1, int(y/scale))
        for x in range(w):
            sx = min(WIDTH-1, int(x/scale))
            i = (sy*WIDTH+sx)*4
            rows.extend(pixels[i:i+4])
    def chunk(kind, data):
        return (struct.pack('!I', len(data)) + kind + data +
                struct.pack('!I', zlib.crc32(kind+data)))
    return (b'\x89PNG\r\n\x1a\n' +
            chunk(b'IHDR', struct.pack('!2I5B', w,h,8,6,0,0,0)) +
            chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b''))


def sprite_layers():
    """Rig the original pixels; their neutral composite equals the reference.

    Small shared joint patches are copies of existing pixels, so they remain
    invisible at rest and cover seams during modest independent motion.
    """
    pixels = sprite_rgba()
    names = ('foot_l', 'foot_r', 'arm_l', 'arm_r', 'torso', 'head')
    layers = {name: bytearray(len(pixels)) for name in names}

    def inside(x, y, points):
        odd = False
        prev = points[-1]
        for point in points:
            if (point[1] > y) != (prev[1] > y):
                crossing = (prev[0]-point[0]) * (y-point[1]) / (prev[1]-point[1]) + point[0]
                if x < crossing:
                    odd = not odd
            prev = point
        return odd

    left = ((9,72),(23,72),(25,80),(35,83),(45,87),(49,94),(41,100),(18,97),(9,89))
    right = ((115,83),(130,82),(132,103),(117,109),(105,104),(100,98),(111,94))
    for y in range(HEIGHT):
        for x in range(WIDTH):
            i = (y*WIDTH+x)*4
            if not pixels[i+3]:
                continue
            if y >= 121 and x < 64:
                part = 'foot_l'
            elif y >= 123:
                part = 'foot_r'
            elif inside(x,y,left):
                part = 'arm_l'
            elif inside(x,y,right):
                part = 'arm_r'
            elif y >= 96:
                part = 'torso'
            else:
                part = 'head'
            layers[part][i:i+4] = pixels[i:i+4]
            # Overlap only existing pixels, never draw new external geometry.
            joints = (('torso', 44 <= x <= 98 and 92 <= y <= 101),
                      ('arm_l', 35 <= x <= 48 and 87 <= y <= 96),
                      ('arm_r', 105 <= x <= 119 and 94 <= y <= 102),
                      ('foot_l', 48 <= x <= 63 and 117 <= y <= 126),
                      ('foot_r', 65 <= x <= 80 and 119 <= y <= 128))
            for name, include in joints:
                if include:
                    layers[name][i:i+4] = pixels[i:i+4]

    # Lift the existing chevron off its screen for gaze and continuous blinks.
    # Full original tile on top restores every reference pixel in the open pose.
    eye = bytearray(len(pixels))
    for y in range(49,73):
        for x in range(59,76):
            i = (y*WIDTH+x)*4
            eye[i:i+4] = pixels[i:i+4]
            sample = (y*WIDTH+80)*4
            layers['head'][i:i+4] = pixels[sample:sample+4]
    for level in range(5):
        frame = bytearray(len(pixels))
        h = max(2, round(24 * (1-.9*level/4)))
        top = 61 - h//2
        for y in range(h):
            source_y = 49 + min(23, int(y*24/h))
            a,b = ((source_y*WIDTH+59)*4, (source_y*WIDTH+76)*4)
            target = ((top+y)*WIDTH+59)*4
            frame[target:target+(b-a)] = eye[a:b]
        layers[f'eye{level}'] = frame
    return {name: bytes(value) for name,value in layers.items()}


class PetRenderer:
    def __init__(self, canvas, scale=1.0, image_factory=None):
        self.canvas, self.scale = canvas, scale
        self.items = {}
        self.pose = None
        self.last_time = None
        factory = image_factory or tk.PhotoImage
        self.images = {name: factory(master=canvas, data=rgba_png(pixels,scale), format='png')
                       for name,pixels in sprite_layers().items()}

    def draw(self, seconds, activity="idle"):
        target = pet_pose(seconds / .06, activity)
        dt = max(0.0, seconds - self.last_time) if self.last_time is not None else 0
        if self.pose is None:
            self.pose = target.copy()
        else:
            for key, value in target.items():
                response = .025 if key == "blink" else .16
                self.pose[key] += (value - self.pose[key]) * (1 - math.exp(-dt / response))
        self.last_time = seconds
        p = self.pose
        x, y = p['lean'], 8+p['hop']
        origins = {
            'foot_l': (x, y+p['bob']*.4+p['feet']*.6),
            'foot_r': (x, y+p['bob']*.4-p['feet']*.6),
            'arm_l': (x-p['left_arm']*.08, y+p['bob']-p['left_arm']*.14+p['arm']*.18),
            'arm_r': (x+p['wave']*.7, y+p['bob']+p['right_arm']*.18-p['arm']*.18),
            'torso': (x*.6, y+p['bob']*.65),
            'head': (x+p['tilt']*.18, y+p['bob']),
        }
        origins['eye'] = (origins['head'][0]+p['look']*.5, origins['head'][1])
        for name, (ox,oy) in origins.items():
            image = self.images[f"eye{round(p['blink']*4)}"] if name == 'eye' else self.images[name]
            if name not in self.items:
                self.items[name] = self.canvas.create_image(
                    ox*self.scale, oy*self.scale, image=image, anchor='nw', tags=('pet','hit'))
            else:
                self.canvas.coords(self.items[name], ox*self.scale, oy*self.scale)
                if name == 'eye':
                    self.canvas.itemconfigure(self.items[name], image=image)
