"""
agents/validator/run_agent.py
------------------------------
Entry point for the Result Validator Agent Flask app.

Usage:
    python agents/validator/run_agent.py
    → http://127.0.0.1:8085
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from flask import Flask
from config import VALIDATOR_PORT
from routers.validator_router import validator_bp

app = Flask(__name__)
app.register_blueprint(validator_bp)

if __name__ == "__main__":
    print(f"\n  Result Validator Agent -- http://127.0.0.1:{VALIDATOR_PORT}\n")
    app.run(debug=False, port=VALIDATOR_PORT, host="127.0.0.1")
