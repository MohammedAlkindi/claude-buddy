import math
import unittest
from unittest import mock

from pip_art import PetRenderer, pet_pose


class NaturalAnimation(unittest.TestCase):
    def renderer(self):
        canvas = mock.Mock()
        canvas.create_polygon.side_effect = range(1, 100)
        return PetRenderer(canvas), canvas

    def test_reuses_hit_targets_instead_of_recreating_every_frame(self):
        renderer, canvas = self.renderer()
        renderer.draw(0)
        count = canvas.create_polygon.call_count
        self.assertGreater(count, 20)
        for i in range(1, 100):
            renderer.draw(i / 60, "working" if i > 50 else "idle")
        self.assertEqual(canvas.create_polygon.call_count, count)
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


if __name__ == "__main__":
    unittest.main()
