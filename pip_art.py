"""Pip's dependency-free artwork and time-based desktop animation.

The canvas keeps its items between frames, so animation never destroys hit
targets. All coordinates are logical pixels; Tk applies the monitor's DPI.
"""
import math


OUTLINE = "#432c29"
CLAY = "#d97757"
SHADOW = "#ba5d44"
DEEP = "#a94f3c"
LIGHT = "#e99a79"
HIGHLIGHT = "#f1b292"
CREAM = "#fff0df"
SCREEN = "#352c30"


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
    return {
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


class PetRenderer:
    def __init__(self, canvas, scale=1.0):
        self.canvas, self.scale = canvas, scale
        self.items = {}
        self.pose = None
        self.last_time = None

    def draw(self, seconds, activity="idle"):
        target = pet_pose(seconds / .06, activity)
        dt = max(0.0, seconds - self.last_time) if self.last_time is not None else 0
        if self.pose is None:
            self.pose = target.copy()
        else:
            # Exponential easing is independent of frame rate, including when
            # a tool event changes the pose halfway through a breathing cycle.
            for key, value in target.items():
                response = .025 if key == "blink" else .16
                self.pose[key] += (value - self.pose[key]) * (1 - math.exp(-dt / response))
        self.last_time = seconds
        p = self.pose

        def transform(points, group):
            out = []
            angle, cx, cy = 0.0, 61, 99
            if group == "head":
                angle, cx, cy = p["tilt"], 64, 85
            elif group == "left":
                angle, cx, cy = p["left_arm"] + p["arm"], 39, 91
            elif group == "right":
                angle, cx, cy = p["right_arm"] - p["arm"], 86, 91
            angle = math.radians(angle)
            for x, y in zip(points[::2], points[1::2]):
                if group == "torso":
                    x = 62 + (x - 62) * (1 + p["breath"])
                    y = 101 + (y - 101) * (1 - p["breath"])
                elif group == "foot_l":
                    y += p["feet"]
                elif group == "foot_r":
                    y -= p["feet"]
                rx = cx + (x-cx)*math.cos(angle) - (y-cy)*math.sin(angle)
                ry = cy + (x-cx)*math.sin(angle) + (y-cy)*math.cos(angle)
                out.extend(((rx + p["lean"]) * self.scale,
                            (ry + p["bob"] + p["hop"]) * self.scale))
            return out

        def shape(name, points, fill, group="head", outline="", width=1.4, smooth=True):
            coords = transform(points, group)
            if name not in self.items:
                self.items[name] = self.canvas.create_polygon(
                    *coords, fill=fill, outline=outline, width=width*self.scale,
                    smooth=smooth, splinesteps=18, tags=("pet", "hit"))
            else:
                item = self.items[name]
                self.canvas.coords(item, *coords)
                self.canvas.itemconfigure(item, fill=fill)

        def panel(name, x1, y1, x2, y2, radius, color, **kwargs):
            r = radius
            shape(name, [x1+r,y1, x2-r,y1, x2,y1, x2,y1+r,
                         x2,y2-r, x2,y2, x2-r,y2, x1+r,y2,
                         x1,y2, x1,y2-r, x1,y1+r, x1,y1], color, **kwargs)

        # Small dangling feet, with different phases rather than rigid marching.
        shape("foot_l", [46,115, 58,117, 56,127, 49,138, 44,140,
                         36,135, 39,129, 41,121], CLAY, "foot_l", OUTLINE)
        shape("foot_r", [66,116, 78,116, 79,125, 74,134, 68,138,
                         61,135, 61,130], SHADOW, "foot_r", OUTLINE)
        shape("sole_l", [37,134, 44,136, 50,133, 47,139, 43,140], DEEP, "foot_l")
        shape("toe_l", [41,129, 45,125, 48,127, 44,132], LIGHT, "foot_l")
        shape("sole_r", [62,132, 68,134, 75,130, 71,136, 67,138], DEEP, "foot_r")

        # Stubby soft mittens wrap around the hood rather than sticking out flat.
        shape("arm_l", [42,87, 34,89, 27,88, 21,82, 17,82, 15,86,
                        12,85, 10,89, 14,96, 23,99, 33,100, 43,95], CLAY, "left", OUTLINE)
        shape("arm_l_shade", [12,91, 21,95, 31,96, 40,92, 37,98, 27,100, 17,97], SHADOW, "left")
        shape("arm_l_light", [16,85, 20,84, 25,90, 19,91], LIGHT, "left")
        shape("arm_r", [82,88, 89,91, 98,87, 104,81, 108,81, 111,84,
                        110,90, 105,97, 97,100, 87,98, 80,94], CLAY, "right", OUTLINE)
        shape("arm_r_shade", [87,96, 96,96, 106,91, 104,97, 95,100, 86,99], SHADOW, "right")

        shape("torso", [45,86, 77,86, 84,96, 82,111, 76,120,
                        62,124, 48,121, 41,113, 40,99], CLAY, "torso", OUTLINE)
        shape("torso_shade", [41,103, 48,115, 61,119, 77,115, 83,106,
                              80,117, 72,123, 54,124, 43,116], SHADOW, "torso")
        shape("torso_light", [46,94, 55,91, 72,93, 78,98, 61,97, 46,98], LIGHT, "torso")
        # Crisp terminal symbols retain the reference's pixel character.
        shape("badge_chevron", [53,102, 57,102, 62,107, 57,112, 53,112, 58,107],
              CREAM, "torso", smooth=False)
        shape("badge_cursor", [65,109, 71,109, 71,112, 65,112], CREAM, "torso", smooth=False)

        # A broad, fluffy hood: paired crown lobes, scalloped cheeks, soft chin.
        hood = [13,49, 17,37, 23,35, 23,27, 32,23, 36,14,
                45,10, 55,11, 61,15, 67,10, 77,11, 85,15,
                89,23, 98,25, 102,34, 109,38, 112,49,
                115,57, 113,69, 115,77, 109,87, 100,92,
                91,97, 75,100, 57,101, 42,98, 30,94,
                23,87, 18,82, 16,73, 12,67, 12,58]
        shape("hood", hood, CLAY, outline=OUTLINE, width=1.8)
        shape("hood_shade", [13,59, 19,70, 22,79, 31,87, 44,92,
                             63,96, 87,93, 104,85, 112,70,
                             114,78, 108,87, 98,94, 82,99,
                             59,101, 42,98, 29,93, 20,84, 16,72], SHADOW)
        shape("hood_glow", [20,48, 23,38, 29,35, 29,29, 37,26,
                            40,18, 48,15, 55,16, 59,20,
                            49,19, 43,23, 40,30, 32,34, 29,41, 24,48], LIGHT)
        shape("crown_glint", [40,18, 48,14, 54,15, 49,17, 44,20], HIGHLIGHT)
        shape("cheek_glow", [18,51, 21,47, 23,52, 22,63, 19,67, 17,61], LIGHT)
        # Face sits slightly right of center, matching the big-hood proportions.
        panel("face_rim", 42,39, 104,89, 10, DEEP, outline=OUTLINE, width=1.7)
        panel("face", 45,41, 102,86, 8, SCREEN)
        panel("screen_reflection", 49,43, 81,45, 1, "#564048")
        shape("screen_bottom", [48,80, 54,82, 94,82, 100,78, 98,85, 52,86], "#2b252b")

        # Eyes compress continuously for a blink; the smile morphs in and out.
        look, blink, smile = p["look"], p["blink"], p["smile"]
        concern = p["concern"]
        eye = [54+look,52, 58+look,52, 65+look,60,
               58+look,68, 54+look,68, 60+look,60]
        happy_eye = [53+look,61, 59+look,55, 65+look,61,
                     65+look,65, 59+look,60, 53+look,65]
        eye = [a+(b-a)*smile for a,b in zip(eye,happy_eye)]
        # Concern raises the inner brow without changing the number of vertices.
        eye[3] -= concern * 2
        eye = [v if i%2==0 else 61+(v-61)*(1-.88*blink) for i,v in enumerate(eye)]
        shape("eye_l", eye, CREAM, smooth=False)
        panel("eye_r", 77+look, 64-5*smile+2*blink,
              91+look, 68-2*smile+blink, 1, CREAM)
