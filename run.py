"""
Smart Mirror — Entry Point
Launch the FastAPI server with Uvicorn.
"""

import uvicorn
from backend.config import SERVER_HOST, SERVER_PORT

if __name__ == "__main__":
    uvicorn.run(
        "backend.server:app",
        host=SERVER_HOST,
        port=SERVER_PORT,
        reload=False,
        log_level="info",
        ws_max_size=16 * 1024 * 1024,  # 16 MB — large enough for base64 frames
    )
