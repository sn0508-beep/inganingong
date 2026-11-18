"""로컬 실행 진입점: python run.py  → http://127.0.0.1:8000"""

import os

from app.server import create_app

app = create_app()

if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    print(f"\n  인수인계서 AI 프로토타입  →  http://{host}:{port}\n")
    app.run(host=host, port=port, debug=False)
