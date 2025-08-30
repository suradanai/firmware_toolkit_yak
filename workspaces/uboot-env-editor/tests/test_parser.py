import unittest
from src.env.parser import parse_env_block
from src.env.editor import edit_env

class TestParser(unittest.TestCase):

    def test_parse_env_block_valid(self):
        env_data = "bootdelay=5\nother_var=value"
        expected_output = {
            "bootdelay": "5",
            "other_var": "value"
        }
        self.assertEqual(parse_env_block(env_data), expected_output)

    def test_parse_env_block_empty(self):
        env_data = ""
        expected_output = {}
        self.assertEqual(parse_env_block(env_data), expected_output)

    def test_parse_env_block_invalid_format(self):
        env_data = "bootdelay5\nother_var=value"
        with self.assertRaises(ValueError):
            parse_env_block(env_data)

class TestEditor(unittest.TestCase):

    def test_edit_env_modify_bootdelay(self):
        env_data = "bootdelay=5\nother_var=value"
        expected_output = "bootdelay=1\nother_var=value"
        modified_env = edit_env(env_data)
        self.assertIn("bootdelay=1", modified_env)

    def test_edit_env_pad_with_nulls(self):
        env_data = "bootdelay=5"
        modified_env = edit_env(env_data)
        self.assertTrue(modified_env.endswith('\0'))

if __name__ == '__main__':
    unittest.main()