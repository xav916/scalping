"""Entry point for the Scalping Decision Tool."""

import uvicorn
from config.settings import HOST, PORT

if __name__ == "__main__":
    uvicorn.run(
        "backend.app:app",
        host=HOST,
        port=PORT,
        reload=True,
        log_level="info",
    )
