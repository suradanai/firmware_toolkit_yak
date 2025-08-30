import unittest
from src.env.crc import calculate_crc

class TestCRC(unittest.TestCase):

    def test_calculate_crc(self):
        test_data = b'Test environment data'
        expected_crc = 0x12345678  # Replace with the expected CRC value for the test data
        self.assertEqual(calculate_crc(test_data), expected_crc)

    def test_calculate_crc_empty(self):
        test_data = b''
        expected_crc = 0x00000000  # Replace with the expected CRC value for empty data
        self.assertEqual(calculate_crc(test_data), expected_crc)

    def test_calculate_crc_large_data(self):
        test_data = b'A' * 1024  # Large data input
        expected_crc = 0x9abcdef0  # Replace with the expected CRC value for the large data
        self.assertEqual(calculate_crc(test_data), expected_crc)

if __name__ == '__main__':
    unittest.main()