from __future__ import annotations

# Test import paths (src before repo root) are configured in pytest.ini: pythonpath.
# Run the font helper before collection; it leaves ordinary platforms untouched.
from _qt_font_bootstrap import bootstrap_text_font_for_offscreen

bootstrap_text_font_for_offscreen()
