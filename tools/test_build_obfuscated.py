import ast
import base64
import hashlib
from pathlib import Path
import tempfile
import unittest
import zlib

from build_obfuscated import native_source, unpack


class BuildTests(unittest.TestCase):
    def test_unpack_checks_integrity_without_executing_loader(self):
        source = "VALUE = 42\n"
        compressed = zlib.compress(source.encode())
        key = bytes(range(32))
        payload = base64.b85encode(bytes(b ^ key[i % len(key)] for i, b in enumerate(compressed)))
        wrapper = (
            "# Generated file. Rebuild from the private source tree; do not edit.\n"
            f"_d=bytes.fromhex({key.hex()!r})\n_e=_a({payload!r})\n"
            f"if _b(_f).hexdigest()!={hashlib.sha256(compressed).hexdigest()!r}:raise RuntimeError()\n"
            "raise AssertionError('loader must never execute')\n"
        )
        with tempfile.TemporaryDirectory() as work:
            path = Path(work) / "module.py"
            path.write_text(wrapper)
            self.assertEqual(unpack(path), source)
            path.write_text(wrapper.replace(hashlib.sha256(compressed).hexdigest(), "0" * 64))
            with self.assertRaisesRegex(ValueError, "Integrity check failed"):
                unpack(path)

    def test_strip_preserves_signatures_strings_and_async_behavior(self):
        source = '''"""module docs"""
class Empty:
    """class docs"""
async def handler(value: str | None = None):
    """handler docs"""
    return f"hello {value}", "keep this string"
'''
        result = native_source(source)
        tree = ast.parse(result)
        self.assertIsNone(ast.get_docstring(tree))
        self.assertIsNone(ast.get_docstring(tree.body[0]))
        self.assertIsNone(ast.get_docstring(tree.body[1]))
        namespace = {}
        exec(compile(result, "test", "exec"), namespace)
        import asyncio
        import inspect
        self.assertTrue(inspect.iscoroutinefunction(namespace["handler"]))
        self.assertEqual(asyncio.run(namespace["handler"]("world")),
                         ("hello world", "keep this string"))
        self.assertEqual(namespace["handler"].__annotations__, {"value": str | None})


if __name__ == "__main__":
    unittest.main()
