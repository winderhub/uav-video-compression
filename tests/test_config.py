import unittest

from desktop_app.video_compressor.config import CpuMode, encoder_threads, required_free_bytes


class ConfigTests(unittest.TestCase):
    def test_cpu_modes_scale_from_logical_processors(self):
        self.assertEqual(encoder_threads(CpuMode.QUIET, 16), 4)
        self.assertEqual(encoder_threads(CpuMode.BALANCED, 16), 8)
        self.assertEqual(encoder_threads(CpuMode.FAST, 16), 12)

    def test_cpu_modes_never_return_zero(self):
        for mode in CpuMode:
            self.assertEqual(encoder_threads(mode, 1), 1)

    def test_required_space_includes_multiplier_and_reserve(self):
        gib = 1024**3
        self.assertEqual(required_free_bytes(4 * gib), 6 * gib)


if __name__ == "__main__":
    unittest.main()
