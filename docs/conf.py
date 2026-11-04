import os
import sys
from importlib.metadata import PackageNotFoundError, version as distribution_version

sys.path.insert(0, os.path.abspath(".."))

project = "supra-sdk"
copyright = "2025, Supra Labs"
author = "Supra Labs"

try:
    release = distribution_version("supra-sdk")
except PackageNotFoundError as error:
    raise RuntimeError(
        "The supra-sdk distribution is not installed, so the documentation version "
        "cannot be read. Run `uv sync` and build with `make build-docs`."
    ) from error
version = release

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx_autodoc_typehints",
]

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

html_theme = "sphinx_rtd_theme"
html_static_path = ["_static"]
html_static_path = ['_static']
html_favicon = '_static/supra_logo.png'

html_theme_options = {
    "navigation_depth": 8,
}
