import os
import sys

sys.path.insert(0, os.path.abspath(".."))
sys.path.insert(0, os.path.abspath("../src"))

project = "snc2fst"

extensions = [
    "sphinx_click",
]

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

html_theme = "alabaster"
html_theme_options = {
    "fixed_sidebar": True,
    "show_powered_by": True,
    "extra_nav_links": {
        "GitHub": "https://github.com/mazadegan/snc2fst",
    },
}
html_static_path = ["_static"]

master_doc = "index"
