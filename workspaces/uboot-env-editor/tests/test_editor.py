import unittest
from src.env.editor import edit_env

class TestEditor(unittest.TestCase):

    def setUp(self):
        self.env_block = b'bootdelay=5\nother_var=value\n'
        self.expected_env_block = b'bootdelay=1\nother_var=value\n' + b'\x00' * (64 - len(self.env_block))

    def test_edit_env(self):
        modified_env_block = edit_env(self.env_block)
        self.assertEqual(modified_env_block, self.expected_env_block)

if __name__ == '__main__':
    unittest.main()