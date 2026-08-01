import unittest

from sor_autoplay.bcd import bcd_long_digits, bcd_nibble_byte, bcd_word, format_score


class BcdTests(unittest.TestCase):
    def test_bcd_byte_digits(self) -> None:
        self.assertEqual(bcd_nibble_byte(0x00), 0)
        self.assertEqual(bcd_nibble_byte(0x03), 3)
        self.assertEqual(bcd_nibble_byte(0x40), 40)
        self.assertEqual(bcd_nibble_byte(0x99), 99)

    def test_bcd_word_timer_values(self) -> None:
        # Wave starts use $40 / $50 / $60 as BCD-looking timer seeds.
        self.assertEqual(bcd_word(0x0040), 40)
        self.assertEqual(bcd_word(0x0050), 50)
        self.assertEqual(bcd_word(0x0060), 60)
        self.assertEqual(bcd_word(0x0039), 39)

    def test_score_packed_bcd(self) -> None:
        self.assertEqual(bcd_long_digits(0x00050000, digits=8), 50_000)
        self.assertEqual(
            bcd_long_digits(0x00999999 & 0x3FFFFFFF, digits=8) % 1_000_000,
            999_999,
        )
        self.assertEqual(format_score(1234), "001234")


if __name__ == "__main__":
    unittest.main()
