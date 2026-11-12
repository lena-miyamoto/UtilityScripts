"""Console entry point for the csv-util.py standalone script.

Entry-point targets must be importable module names; ``csv-util`` is not a
valid identifier, so this module loads the script with ``runpy`` and lets its
own ``__main__`` block run the CLI.
"""

import runpy
from pathlib import Path


def main():
    runpy.run_path(
        str(Path(__file__).with_name("csv-util.py")),
        run_name="__main__",
    )
