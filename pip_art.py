"""Complete native Codex atlas frames, in Claude colors.

The source is the locally installed Codex v6 atlas, not a screenshot cutout.
Timing and geometry follow the documented Codex sprite contract. No image
library or Codex installation is needed at runtime.
"""
import functools
import math
from pathlib import Path
import struct
import tkinter as tk
import zlib

CELL_WIDTH, CELL_HEIGHT = 192, 208
ATLAS_WIDTH, ATLAS_HEIGHT = 1536, 2288
DISPLAY_WIDTH = 112.64  # installed renderer default: 7.04rem at 16px/rem
DISPLAY_HEIGHT = DISPLAY_WIDTH * CELL_HEIGHT / CELL_WIDTH
ORIGIN_X, ORIGIN_Y = 8, 0
ASSET = Path(__file__).resolve().parent / 'assets' / 'codex-v6.rgba.z'
ANIMATIONS = {
    'idle': (0, (1680, 660, 660, 840, 840, 1920)),
    'running-right': (1, (120,)*7+(220,)),
    'running-left': (2, (120,)*7+(220,)),
    'waving': (3, (140,140,140,280)),
    'jumping': (4, (140,140,140,140,280)),
    'failed': (5, (140,)*7+(240,)),
    'waiting': (6, (150,)*5+(260,)),
    'running': (7, (120,)*5+(220,)),
    'review': (8, (150,)*5+(280,)),
}
ACTIVITIES = {'idle':'idle', 'thinking':'review', 'working':'running',
              'happy':'jumping', 'error':'failed', 'dragging':'running'}


def smoothstep(value):
    value = min(1.0,max(0.0,value))
    return value*value*(3-2*value)


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



@functools.lru_cache(maxsize=1)
def atlas_rgba():
    pixels = zlib.decompress(ASSET.read_bytes())
    if len(pixels) != ATLAS_WIDTH * ATLAS_HEIGHT * 4:
        raise ValueError('Invalid Pip atlas size')
    return pixels


@functools.lru_cache(maxsize=80)
def frame_rgba(row, column):
    if not (0 <= row < 11 and 0 <= column < 8):
        raise ValueError('Invalid Pip atlas cell')
    source = atlas_rgba()
    pixels = bytearray()
    for y in range(row*CELL_HEIGHT,(row+1)*CELL_HEIGHT):
        start=(y*ATLAS_WIDTH+column*CELL_WIDTH)*4
        pixels.extend(source[start:start+CELL_WIDTH*4])
    for i in range(0,len(pixels),4):
        if pixels[i+3]:
            pixels[i:i+3] = bytes(claude_pixel(*pixels[i:i+3]))
    return bytes(pixels)


def frame_at(state, elapsed):
    """Elapsed-time lookup preserves residual time after a delayed UI tick."""
    row,durations = ANIMATIONS[state]
    phase = max(0,elapsed)*1000 % sum(durations)
    for column,duration in enumerate(durations):
        if phase < duration:
            return row,column
        phase -= duration
    return row,0


def look_frame(x,y,width=DISPLAY_WIDTH,height=DISPLAY_HEIGHT):
    dx,dy = x-width/2,y-height/2
    if math.hypot(dx,dy) <= 1:
        return None
    direction = int(((math.degrees(math.atan2(dx,-dy))+360)%360+11.25)//22.5)%16
    return 9+direction//8,direction%8


@functools.lru_cache(maxsize=192)
def frame_png(row,column,scale=1.0,colorkey=False):
    pixels=frame_rgba(row,column)
    w,h=round(DISPLAY_WIDTH*scale),round(DISPLAY_HEIGHT*scale)
    rows=bytearray()
    for y in range(h):
        rows.append(0)
        sy=min(CELL_HEIGHT-1,int((y+.5)*CELL_HEIGHT/h))
        for x in range(w):
            sx=min(CELL_WIDTH-1,int((x+.5)*CELL_WIDTH/w))
            i=(sy*CELL_WIDTH+sx)*4
            r,g,b,a=pixels[i:i+4]
            # Tk's Windows color-key surface cannot composite partial alpha.
            # Use crisp coverage rather than blending edges against magenta.
            if colorkey:
                a=255 if a>=128 else 0
            rows.extend((r,g,b,a))
    def chunk(kind,data):
        return struct.pack('!I',len(data))+kind+data+struct.pack('!I',zlib.crc32(kind+data))
    return (b'\x89PNG\r\n\x1a\n'+
            chunk(b'IHDR',struct.pack('!2I5B',w,h,8,6,0,0,0))+
            chunk(b'IDAT',zlib.compress(rows))+chunk(b'IEND',b''))


class PetRenderer:
    def __init__(self,canvas,scale=1.0,image_factory=None):
        self.canvas,self.scale=canvas,scale
        self.factory=image_factory or tk.PhotoImage
        self.images={}
        self.items={}
        self.state=None
        self.state_started=0.0
        self.pointer=None
        self.current_cell=(0,0)

    def set_pointer(self,x,y):
        self.pointer=((x/self.scale)-ORIGIN_X,(y/self.scale)-ORIGIN_Y)

    def draw(self,seconds,activity='idle'):
        state=ACTIVITIES.get(activity,activity if activity in ANIMATIONS else 'idle')
        if state != self.state:
            self.state,self.state_started=state,seconds
        elapsed=max(0,seconds-self.state_started)
        cell=frame_at(state,elapsed)
        # The extra two atlas rows contain the authored 16-direction poses.
        # Use them when the pointer is near Pip; leave idle breathing elsewhere.
        gazing=False
        if state=='idle' and self.pointer is not None:
            x,y=self.pointer
            if -24<=x<=DISPLAY_WIDTH+24 and -24<=y<=DISPLAY_HEIGHT+24:
                cell=look_frame(x,y) or cell
                gazing=True
        if state=='idle' and not gazing and 12<=seconds%18<14.1:
            cell=frame_at('waving',seconds%18-12)
        self.current_cell=cell
        if cell not in self.images:
            self.images[cell]=self.factory(master=self.canvas,
                data=frame_png(*cell,self.scale,True),format='png')
        image=self.images[cell]
        if not self.items:
            self.items['sprite']=self.canvas.create_image(ORIGIN_X*self.scale,
                ORIGIN_Y*self.scale,image=image,anchor='nw',tags=('pet','hit'))
        else:
            self.canvas.itemconfigure(self.items['sprite'],image=image)
