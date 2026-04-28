"""
agents/generator/run_agent.py
------------------------------
Entry point for the Test Case Generator Flask app.

Usage:
    python agents/generator/run_agent.py
    → http://127.0.0.1:8083
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from flask import Flask
from config import GENERATOR_PORT
from routers.generator_router import generator_bp

app = Flask(__name__)
app.register_blueprint(generator_bp)

if __name__ == "__main__":
    print(f"\n  Test Case Generator -- http://0.0.0.0:{GENERATOR_PORT}\n")
    app.run(debug=False, port=GENERATOR_PORT, host="0.0.0.0")
