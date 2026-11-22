#!/usr/bin/env python3
"""Точка входа: python st.py <команда>  (Windows: py st.py <команда>). Справка: python st.py -h"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools"))
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

from strateg.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
