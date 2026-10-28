import math
import unittest
from unittest import mock

from pip_art import PetRenderer, pet_pose, claude_pixel, sprite_rgba, sprite_png, sprite_layers
from pip_pixels import PIXELS, WIDTH, HEIGHT


class NaturalAnimation(unittest.TestCase):
    def renderer(self):
        canvas = mock.Mock()
        canvas.create_image.side_effect = range(1,100)
        return PetRenderer(canvas, image_factory=mock.Mock()), canvas

    def test_reuses_hit_targets_instead_of_recreating_every_frame(self):
        renderer, canvas = self.renderer()
        renderer.draw(0)
        self.assertEqual(canvas.create_image.call_count, 7)
        for i in range(1, 100):
            renderer.draw(i / 60, "working" if i > 50 else "idle")
        self.assertEqual(canvas.create_image.call_count, 7)
        canvas.create_polygon.assert_not_called()
        canvas.delete.assert_not_called()

    def test_activity_change_eases_in_and_settles(self):
        renderer, _ = self.renderer()
        renderer.draw(0, "idle")
        renderer.draw(.016, "happy")
        self.assertGreater(renderer.pose["smile"], 0)
        self.assertLess(renderer.pose["smile"], .15)
        for i in range(2, 100):
            renderer.draw(i * .016, "happy")
        self.assertGreater(renderer.pose["smile"], .999)
        renderer.draw(1.6, "idle")
        self.assertGreater(renderer.pose["smile"], .8)

    def test_transition_response_is_independent_of_frame_rate(self):
        values = []
        for fps in (30, 60, 120):
            renderer, _ = self.renderer()
            renderer.draw(0, "idle")
            for i in range(1, fps+1):
                renderer.draw(i/fps, "happy")
            values.append(renderer.pose["smile"])
        self.assertLess(max(values) - min(values), 1e-10)

    def test_motion_is_fractional_and_continuous(self):
        before, after = pet_pose(10), pet_pose(10 + .016/.06)
        self.assertNotEqual(before["bob"], round(before["bob"]))
        self.assertLess(abs(after["bob"] - before["bob"]), .06)
        for activity in ("idle", "thinking", "working", "happy", "error", "dragging"):
            for i in range(1000):
                self.assertTrue(all(math.isfinite(v) for v in pet_pose(i/4, activity).values()))


class ReferenceFidelity(unittest.TestCase):
    def test_neutral_rig_composites_to_exact_reference_colors_and_geometry(self):
        layers = sprite_layers()
        composite = bytearray(WIDTH*HEIGHT*4)
        for name in ('foot_l','foot_r','arm_l','arm_r','torso','head','eye0'):
            pixels = layers[name]
            for i in range(0,len(pixels),4):
                if pixels[i+3]:
                    composite[i:i+4] = pixels[i:i+4]
        self.assertEqual(bytes(composite), sprite_rgba())

    def test_reference_pose_has_no_layer_offsets(self):
        self.assertTrue(all(value == 0 for value in pet_pose(123,'reference').values()))

    def test_palette_swap_preserves_every_alpha_pixel(self):
        tinted = sprite_rgba()
        self.assertEqual(len(tinted), WIDTH * HEIGHT * 4)
        self.assertEqual(tinted[3::4], PIXELS[3::4])
        self.assertEqual(sum(a > 0 for a in tinted[3::4]), 12564)

    def test_main_blue_maps_to_claude_terracotta(self):
        self.assertEqual(claude_pixel(131, 158, 243), (217, 119, 87))
        self.assertEqual(claude_pixel(4, 4, 4), (4, 4, 4))
        cream = claude_pixel(180, 240, 242)
        self.assertGreater(cream[0], cream[1])
        self.assertGreater(cream[1], cream[2])

    def test_dpi_png_dimensions_follow_the_reference(self):
        import struct
        for scale in (1, 1.25, 1.5, 2):
            png = sprite_png(scale)
            self.assertEqual(png[:8], b'\x89PNG\r\n\x1a\n')
            self.assertEqual(struct.unpack('!2I', png[16:24]),
                             (round(WIDTH*scale), round(HEIGHT*scale)))


if __name__ == "__main__":
    unittest.main()
