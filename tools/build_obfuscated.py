"""Build source-free native modules from the project's existing packed sources."""
import argparse
import ast
import base64
import hashlib
import importlib.machinery
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import zlib

ROOT = Path(__file__).resolve().parents[1]
MODULES = ("main", "pages", "relay_vless", "speed_limit", "telegram_bot", "xhttp_siz10")


def unpack(path):
    """Read literals only: never execute the input loader during a build."""
    source = path.read_text(encoding="utf-8")
    if not source.startswith("# Generated file. Rebuild from the private source tree;"):
        ast.parse(source)
        return source
    tree = ast.parse(source)
    assignments = {
        node.targets[0].id: node.value
        for node in tree.body
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
    }
    key = bytes.fromhex(ast.literal_eval(assignments["_d"].args[0]))
    payload = base64.b85decode(ast.literal_eval(assignments["_e"].args[0]))
    compressed = bytes(value ^ key[i % len(key)] for i, value in enumerate(payload))
    check = next(node for node in tree.body if isinstance(node, ast.If))
    expected = ast.literal_eval(check.test.comparators[0])
    if hashlib.sha256(compressed).hexdigest() != expected:
        raise ValueError(f"Integrity check failed: {path.name}")
    result = zlib.decompress(compressed).decode("utf-8")
    ast.parse(result)
    return result


class StripDocumentation(ast.NodeTransformer):
    def strip(self, node):
        self.generic_visit(node)
        if (node.body and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)):
            node.body.pop(0)
            if not node.body:
                node.body.append(ast.Pass())
        return node

    visit_Module = strip
    visit_ClassDef = strip
    visit_FunctionDef = strip
    visit_AsyncFunctionDef = strip


def native_source(source):
    tree = StripDocumentation().visit(ast.parse(source))
    return ast.unparse(ast.fix_missing_locations(tree)) + "\n"


def compile_modules(stage):
    from Cython.Build import cythonize
    from Cython.Compiler import Options
    from setuptools import Distribution, Extension

    Options.docstrings = False
    Options.embed_pos_in_docstring = False
    flags = ["-O3", "-g0", "-fvisibility=hidden", "-flto"]
    link_flags = ["-flto"]
    if sys.platform == "linux":
        link_flags += ["-Wl,--strip-all", "-Wl,-z,relro,-z,now"]
    extensions = [
        Extension(name, [f"{name}.py"], extra_compile_args=flags,
                  extra_link_args=link_flags,
                  define_macros=[("CYTHON_CLINE_IN_TRACEBACK", "0")])
        for name in MODULES
    ]
    dist = Distribution({"name": "x4g-native", "ext_modules": cythonize(
        extensions, quiet=True, build_dir="c",
        compiler_directives={
            "language_level": 3, "binding": True, "annotation_typing": False,
            "infer_types": False, "embedsignature": False,
            "emit_code_comments": False, "linetrace": False, "profile": False,
        },
    )})
    command = dist.get_command_obj("build_ext")
    command.build_lib = str(stage)
    command.build_temp = "objects"
    dist.run_command("build_ext")
    for binary in stage.iterdir():
        subprocess.run(["strip", "-x" if sys.platform == "darwin" else "--strip-unneeded",
                        str(binary)], check=True)


def build(output):
    if sys.platform not in ("darwin", "linux"):
        raise RuntimeError("Build on Linux or macOS with a C compiler and strip installed")
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite {output}; choose a new --output directory")
    sources = {name: unpack(ROOT / f"{name}.py") for name in MODULES}
    output.parent.mkdir(parents=True, exist_ok=True)
    # Only a verified, allowlisted release escapes this private temporary directory.
    with tempfile.TemporaryDirectory(prefix="x4g-native-") as work:
        work = Path(work)
        stage = work / "release"
        stage.mkdir()
        for name, source in sources.items():
            (work / f"{name}.py").write_text(native_source(source), encoding="utf-8")
        previous = Path.cwd()
        try:
            os.chdir(work)
            compile_modules(stage)
        finally:
            os.chdir(previous)
        for name in MODULES:
            matches = [p for p in stage.iterdir() if any(
                p.name == name + suffix for suffix in importlib.machinery.EXTENSION_SUFFIXES)]
            if len(matches) != 1:
                raise RuntimeError(f"Missing or ambiguous compiled module: {name}")
        if len(list(stage.iterdir())) != len(MODULES):
            raise RuntimeError("Unexpected release artifact")
        (stage / "run.py").write_text(
            'import main\nimport uvicorn\n\nif __name__ == "__main__":\n'
            '    uvicorn.run("main:app", host="0.0.0.0", port=main.CONFIG["port"], '
            'log_level="info", workers=1)\n', encoding="utf-8")
        shutil.copy2(ROOT / "requirements.txt", stage / "requirements.txt")
        subprocess.run([sys.executable, str(ROOT / "tools/verify_release.py"), str(stage)],
                       check=True, cwd=work)
        manifest = {
            "python": platform.python_version(), "platform": platform.platform(),
            "architecture": platform.machine(),
            "files": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in stage.iterdir() if p.is_file()},
        }
        (stage / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        # copytree refuses an existing destination, including a concurrent build's.
        shutil.copytree(stage, output, ignore=shutil.ignore_patterns("__pycache__"))
    print(f"Verified native release: {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist/native")
    args = parser.parse_args()
    build(args.output.resolve())
