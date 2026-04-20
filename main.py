#!/usr/bin/env python3
"""Entry point: python main.py [options]"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from overcook.game import main

if __name__ == "__main__":
    main()
