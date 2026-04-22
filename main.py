#!/usr/bin/env python3
"""Entry point: python main.py [options]"""
import sys
import os
import logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# gesture_dnn 로거: 프레임별 DNN 입력/확률 로그를 파일에 기록
_log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gesture_dnn.log")
_gesture_logger = logging.getLogger("gesture_dnn")
_gesture_logger.setLevel(logging.DEBUG)
_fh = logging.FileHandler(_log_path, mode="w", encoding="utf-8")
_fh.setFormatter(logging.Formatter("%(asctime)s %(message)s", datefmt="%H:%M:%S"))
_gesture_logger.addHandler(_fh)

from overcook.runloop import main

if __name__ == "__main__":
    main()
