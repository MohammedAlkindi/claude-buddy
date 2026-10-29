"""Checks against the source atlas, frame cadence, and installed display size."""
import hashlib
import json
from pathlib import Path
import struct
import unittest
from unittest import mock

from pip_art import (ANIMATIONS, ACTIVITIES, ATLAS_WIDTH, CELL_WIDTH, CELL_HEIGHT,
                     DISPLAY_WIDTH, DISPLAY_HEIGHT, PetRenderer, atlas_rgba,
                     claude_pixel, frame_at, frame_png, frame_rgba, look_frame)


class NativeAtlas(unittest.TestCase):
    def test_source_matches_recorded_native_asset_hash(self):
        meta=json.loads((Path(__file__).resolve().parent.parent/'assets/codex-v6.json').read_text())
        self.assertEqual(hashlib.sha256(atlas_rgba()).hexdigest(),meta['rgba_sha256'])

    def test_every_used_frame_preserves_alpha_and_source_geometry(self):
        source=atlas_rgba()
        for state,(row,durations) in ANIMATIONS.items():
            for col in range(len(durations)):
                raw=frame_rgba(row,col)
                for y in range(CELL_HEIGHT):
                    a=((row*CELL_HEIGHT+y)*ATLAS_WIDTH+col*CELL_WIDTH)*4
                    source_row=source[a:a+CELL_WIDTH*4]
                    self.assertEqual(raw[y*CELL_WIDTH*4+3:(y+1)*CELL_WIDTH*4:4],source_row[3::4])
        self.assertEqual(claude_pixel(131,158,243),(217,119,87))

    def test_display_size_matches_codex_css_without_double_dpi(self):
        self.assertEqual(DISPLAY_WIDTH,7.04*16)
        for dpi in (1,1.25,1.5,2):
            png=frame_png(0,0,dpi)
            self.assertEqual(struct.unpack('!2I',png[16:24]),
                             (round(DISPLAY_WIDTH*dpi),round(DISPLAY_HEIGHT*dpi)))


class Playback(unittest.TestCase):
    def test_idle_loop_is_6_6_seconds(self):
        self.assertEqual(sum(ANIMATIONS['idle'][1]),6600)
        self.assertEqual(frame_at('idle',1.679),(0,0))
        self.assertEqual(frame_at('idle',1.68),(0,1))
        self.assertEqual(frame_at('idle',6.6),(0,0))

    def test_timing_handles_long_or_irregular_ui_delays(self):
        for state in ANIMATIONS:
            cycle=sum(ANIMATIONS[state][1])/1000
            for t in (.01,.135,.789):
                self.assertEqual(frame_at(state,t),frame_at(state,t+cycle*20))

    def test_state_change_starts_on_first_authored_pose(self):
        canvas=mock.Mock();canvas.create_image.return_value=1
        renderer=PetRenderer(canvas,image_factory=mock.Mock())
        renderer.draw(10,'idle')
        renderer.draw(11,'working')
        self.assertEqual(renderer.current_cell,(7,0))
        renderer.draw(11.13,'working')
        self.assertEqual(renderer.current_cell,(7,1))
        renderer.draw(15,'happy')
        self.assertEqual(renderer.current_cell,(4,0))
        self.assertEqual(canvas.create_image.call_count,1)
        canvas.delete.assert_not_called()

    def test_all_sixteen_authored_look_directions(self):
        import math
        for direction in range(16):
            angle=math.radians(direction*22.5)
            x=DISPLAY_WIDTH/2+math.sin(angle)*100
            y=DISPLAY_HEIGHT/2-math.cos(angle)*100
            self.assertEqual(look_frame(x,y),(9+direction//8,direction%8))
        self.assertIsNone(look_frame(DISPLAY_WIDTH/2,DISPLAY_HEIGHT/2))

    def test_complete_frames_have_different_limb_pixels(self):
        # Native run-cycle lower-body frames must actually differ, not translate
        # disconnected pieces of a static screenshot.
        a,b=frame_rgba(7,0),frame_rgba(7,1)
        self.assertNotEqual(a[140*CELL_WIDTH*4:],b[140*CELL_WIDTH*4:])


if __name__=='__main__':
    unittest.main()
