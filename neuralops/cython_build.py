"""
cython_build.py — compile the app to native code for the release image
(owner, 2026-11-01: "make sure the docker contains no code but compiled one").

Every module of nucleus and the engine becomes a native extension module
(`<name>.cpython-313-<arch>-linux-gnu.so`) BESIDE where its .py was, so
imports, Django's discovery and celery/uvicorn's "module:attr" strings keep
working unchanged. Python bytecode (.pyc) is easy to turn back into readable
code; native machine code is not.

Kept as bytecode on purpose (compiled again afterwards by compileall -b):
  - manage.py           — 20 lines of Django boilerplate, stays readable
  - __init__.py         — package markers; a compiled __init__ changes how
                          a package's __path__ behaves for little gain
  - migrations/*.py     — Django lists and loads them as plain modules; they
                          only describe database tables

Run inside the code-builder stage:  python cython_build.py /code/nucleus /code/ai
A module that fails to compile fails the BUILD. A module that compiles but
misbehaves at run time goes on FALLBACK below — with the reason — and stays
bytecode; the test suites run against the compiled image are the proof.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from Cython.Build import cythonize
from setuptools import Extension, setup

KEEP_NAMES = {"manage.py", "__init__.py"}
KEEP_DIRS = {"migrations"}

# path relative to its root → why it stays bytecode. Empty until a test run
# proves a module needs it.
FALLBACK: dict[str, str] = {}

DIRECTIVES = {
    "language_level": 3,
    # Function objects that behave like Python functions: inspect.signature,
    # __annotations__, keyword calls — Django Ninja, pydantic-ai tool schemas
    # and FastAPI all read them.
    "binding": True,
    "always_allow_keywords": True,
    # NEVER turn annotations into C types: `x: int = None` must stay Python
    # semantics, and pydantic/dataclasses read the annotations themselves.
    "annotation_typing": False,
    # Docstrings stay: pydantic-ai tool descriptions and API docs come from them.
}


def stays_bytecode(root: Path, path: Path) -> bool:
    rel = path.relative_to(root)
    return (path.name in KEEP_NAMES
            or any(part in KEEP_DIRS for part in rel.parts[:-1])
            or str(rel) in FALLBACK)


def module_name(root: Path, path: Path) -> str:
    return ".".join(path.relative_to(root).with_suffix("").parts)


def compile_root(root: Path, jobs: int) -> int:
    sources = sorted(p for p in root.rglob("*.py") if not stays_bytecode(root, p))
    if not sources:
        return 0
    extensions = [Extension(module_name(root, p), [str(p.relative_to(root))]) for p in sources]
    build_tmp = Path("/tmp/cython-build") / root.name
    here = Path.cwd()
    os.chdir(root)
    try:
        setup(
            name=f"neuralops-{root.name}",
            ext_modules=cythonize(extensions, compiler_directives=DIRECTIVES,
                                  nthreads=jobs, quiet=True, build_dir=str(build_tmp / "c")),
            script_args=["build_ext", "--inplace", "-j", str(jobs), "--build-temp", str(build_tmp / "o")],
        )
    finally:
        os.chdir(here)
    # Only now that every extension built: remove the sources it replaced.
    for path in sources:
        built = list(path.parent.glob(path.stem + ".cpython-*.so"))
        if not built:
            raise SystemExit(f"no native module was built for {path}")
        path.unlink()
    shutil.rmtree(build_tmp, ignore_errors=True)
    shutil.rmtree(root / "build", ignore_errors=True)
    return len(sources)


def main() -> None:
    roots = [Path(r) for r in (sys.argv[1:] or ["/code/nucleus", "/code/ai"])]
    jobs = max(1, os.cpu_count() or 1)
    for root in roots:
        count = compile_root(root, jobs)
        print(f"[cython] {root}: {count} modules compiled to native code")
    leftovers = [str(p) for r in roots for p in r.rglob("*.c")]
    if leftovers:
        raise SystemExit(f"generated C sources left behind: {leftovers[:5]}")


if __name__ == "__main__":
    main()
