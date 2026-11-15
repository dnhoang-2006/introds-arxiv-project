"""Cấu hình pytest dùng chung: cho phép import trực tiếp các module trong src/."""
import sys
import importlib.util
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

# Tránh xung đột với module built-in 'parser' trên Python < 3.10
src_parser = SRC_DIR / "parser" / "__init__.py"
if src_parser.exists() and (
    "parser" in sys.builtin_module_names
    or "parser" not in sys.modules
    or not hasattr(sys.modules.get("parser"), "__path__")
):
    spec = importlib.util.spec_from_file_location(
        "parser",
        src_parser,
        submodule_search_locations=[str(src_parser.parent)],
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["parser"] = mod
    spec.loader.exec_module(mod)
