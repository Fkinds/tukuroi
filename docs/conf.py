# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

# Configuration file for the Sphinx documentation builder.
#
# This file only contains a selection of the most common options. For a full
# list see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Path setup --------------------------------------------------------------

# If extensions (or modules to document with autodoc) are in another directory,
# add these directories to sys.path here. If the directory is relative to the
# documentation root, use os.path.abspath to make it absolute, like shown here.
#
# import os
# import sys
# sys.path.insert(0, os.path.abspath('.'))

# -- Patch python domain signature regex to allow "foo-bar" style names ------

import re

# modified from sphinx/domains/python.py
py_sig_re = re.compile(
    r'''^ ([\w.]*\.)?            # class name(s)
          ([\w-]+)  \s*             # thing name
          (?: \(\s*(.*)\s*\)     # optional: arguments
           (?:\s* -> \s* (.*))?  #           return annotation
          )? $                   # and nothing more
          ''', re.VERBOSE)

from sphinx.domains import python

python.py_sig_re = py_sig_re

# -- Project information -----------------------------------------------------

project = "tukuroi"
copyright = f" Copyright © Meta Platforms, Inc. and affiliates"
author = ""
# -- General configuration ---------------------------------------------------

# Add any Sphinx extension module names here, as strings. They can be
# extensions coming with Sphinx (named 'sphinx.ext.*') or your custom
# ones.
extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.intersphinx",
    "sphinx_mdinclude",
]

# List of patterns, relative to source directory, that match files and
# directories to ignore when looking for source files.
# This pattern also affects html_static_path and html_extra_path.
exclude_patterns = [
    # included in other docs
    "guide/*.rst"
]

autodoc_default_options = {
    "members": True,
    "undoc-members": True,
}
autodoc_member_order = "groupwise"
autodoc_typehints = "description"
autodoc_typehints_format = "short"

# highlight_language = "python3"
# The inventories that the docs refer to, fetched on each build: a stalled
# connection gives up after intersphinx_timeout seconds, as a warning that
# fails the build (-W of `make html`, #155).
intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
}
intersphinx_timeout = 30
master_doc = "index"

# -- Options for HTML output -------------------------------------------------

# The theme to use for HTML and HTML Help pages.  See the documentation for
# a list of builtin themes.
#
html_theme = "alabaster"
html_theme_options = {
    "description": "Advanced linting framework",
    "fixed_sidebar": True,
    "badge_branch": "master",
    "github_button": False,
    "github_user": "Fkinds",
    "github_repo": "tukuroi",
    "show_powered_by": False,
    "sidebar_collapse": False,
    "extra_nav_links": {
        "Source": "https://github.com/Fkinds/tukuroi",
        "Report Issues": "https://github.com/Fkinds/tukuroi/issues",
    },
}

html_sidebars = {
    "**": [
        "about.html",
        "navigation.html",
        "relations.html",
        "searchbox.html",
    ],
}

# Add any paths that contain custom static files (such as style sheets) here,
# relative to this directory. They are copied after the builtin static files,
# so a file named "default.css" will overwrite the builtin "default.css".
html_static_path = ["_static"]


# -- A builtin in a type, as Python's -----------------------------------------

import builtins

from docutils import nodes
from sphinx import addnodes
from sphinx.application import Sphinx


def builtins_of_python(app: Sphinx, doctree: nodes.document) -> None:
    """
    A type in a signature or a field is looked for in the names that end with
    it too: ``type`` in ``type[ast.AST]`` would link to ``tukuroi.Error.type``,
    or to ``tukuroi.Token.type`` (#203). A builtin is looked for by its name
    alone, which the Python docs have (intersphinx).
    """
    for node in doctree.findall(addnodes.pending_xref):
        if node.get("refdomain") == "py" and hasattr(builtins, node["reftarget"]):
            node.attributes.pop("refspecific", None)


def setup(app: Sphinx) -> None:
    app.connect("doctree-read", builtins_of_python)
