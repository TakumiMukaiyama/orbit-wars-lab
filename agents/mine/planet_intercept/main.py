"""
提出エントリポイント。
Kaggle は main.py ルートの agent 関数を呼び出す。
src/ 配下のコードをバンドルして提出する場合もこのファイルが起点。
"""

import sys
import os

sys.path.insert(0, os.path.dirname(__name__))

from src.agent import agent  # noqa: F401, E402
