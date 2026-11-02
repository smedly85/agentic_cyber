"""Compatibility entry point for the consolidated cross-language recorder."""
from pathlib import Path
import runpy
runpy.run_path(str(Path(__file__).with_name('audit_cross_language.py')), run_name='__main__')
