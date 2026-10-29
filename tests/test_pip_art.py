import struct
import unittest
import zlib
from unittest import mock
from pip_art import PetRenderer, frame_png, frame_rgba, DISPLAY_WIDTH, DISPLAY_HEIGHT


def png_rows(png):
    width,height=struct.unpack('!2I',png[16:24]); offset=8; chunks=[]
    while offset<len(png):
        n=struct.unpack('!I',png[offset:offset+4])[0]
        if png[offset+4:offset+8]==b'IDAT':chunks.append(png[offset+8:offset+8+n])
        offset+=n+12
    raw=zlib.decompress(b''.join(chunks));stride=width*4+1
    assert all(raw[y*stride]==0 for y in range(height))
    return width,height,b''.join(raw[y*stride+1:(y+1)*stride] for y in range(height))


class SpriteRendering(unittest.TestCase):
    def test_transparency_has_no_magenta_blended_fringe(self):
        w,h,rgba=png_rows(frame_png(0,0,1.5,True))
        self.assertEqual(set(rgba[3::4]),{0,255})
        self.assertTrue(any(rgba[3::4]))
        for i in range(0,len(rgba),4):
            if rgba[i+3]:self.assertNotEqual(rgba[i:i+3],bytes((255,0,255)))

    def test_nearest_sampling_preserves_the_actual_authored_pixels(self):
        source=frame_rgba(3,2)
        for scale in (1,1.5):
            w,h,rgba=png_rows(frame_png(3,2,scale))
            for y in range(h):
                sy=min(207,int((y+.5)*208/h))
                for x in range(w):
                    sx=min(191,int((x+.5)*192/w));i=(sy*192+sx)*4;j=(y*w+x)*4
                    self.assertEqual(rgba[j:j+4],source[i:i+4])

    def test_renderer_caches_images_and_keeps_one_stable_hit_target(self):
        canvas=mock.Mock();canvas.create_image.return_value=1;factory=mock.Mock()
        renderer=PetRenderer(canvas,image_factory=factory)
        for i in range(660):renderer.draw(i/100,'idle')
        self.assertEqual(canvas.create_image.call_count,1)
        self.assertEqual(factory.call_count,6)
        self.assertEqual(len(renderer.images),6)
        canvas.coords.assert_not_called()
        canvas.delete.assert_not_called()

    def test_invalid_atlas_cells_are_rejected(self):
        for cell in ((-1,0),(11,0),(0,8)):
            with self.assertRaises(ValueError):frame_rgba(*cell)

    def test_control_strip_can_fit_below_without_overlaying_the_pet(self):
        self.assertLess(DISPLAY_HEIGHT,128)
        self.assertLess(8+DISPLAY_WIDTH,128)
        self.assertLess(132+28,166)


if __name__=='__main__':unittest.main()
