import os
import sys
from importlib import metadata

sys.path.insert(0, os.path.abspath(".."))

project = "ledgercore"
copyright = "2026, ledgercore contributors"
author = "ledgercore contributors"

try:
    release = metadata.version("ledgercore")
except metadata.PackageNotFoundError:
    try:
        from ledgercore._version import __version__ as release
    except ImportError:
        release = "0.0.0"

version = ".".join(release.split(".")[:2])

extensions = [
    "myst_parser",
    "sphinx.ext.autodoc",
    "sphinx.ext.coverage",
    "sphinx.ext.viewcode",
]

source_suffix = {
    ".md": "markdown",
}

master_doc = "index"

myst_enable_extensions = [
    "colon_fence",
    "deflist",
]

myst_heading_anchors = 3

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

html_theme = "sphinx_rtd_theme"

autodoc_default_options = {
    "members": True,
    "member-order": "bysource",
    "special-members": "__init__",
    "undoc-members": True,
    "exclude-members": "__weakref__",
}

napoleon_google_docstring = True
napoleon_numpy_docstring = True
napoleon_include_init_with_doc = False
napoleon_include_private_with_doc = False
napoleon_include_special_with_doc = True
napoleon_use_admonition_for_examples = False
napoleon_use_admonition_for_notes = False
napoleon_use_admonition_for_references = False
napoleon_use_ivar = False
napoleon_use_param = True
napoleon_use_rtype = True

# intersphinx is intentionally not configured. The current documentation does
# not contain cross-project Python references; re-enabling it requires both
# real references and a release-process policy for offline or cached
# inventories.
todo_include_todos = True
