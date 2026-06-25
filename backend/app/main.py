import os
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from .api.routes_generate import router as generate_router

app = FastAPI()

# Configure CORS - allow all origins for development
# In production, restrict to specific origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for dev; restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Calculate absolute path to the frontend directory relative to this file
# backend/app/main.py -> backend/app -> backend -> root workspace -> frontend
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(os.path.dirname(current_dir))
frontend_dir = os.path.join(root_dir, "frontend")

# Ensure output directory exists at backend level
os.makedirs(os.path.join(os.path.dirname(current_dir), "output"), exist_ok=True)

# Mount the static files (css, js) under /static
app.mount("/static", StaticFiles(directory=frontend_dir), name="static")
app.mount("/vendor", StaticFiles(directory=os.path.join(frontend_dir, "vendor")), name="vendor")

@app.get("/", response_class=HTMLResponse)
def root():
    index_path = os.path.join(frontend_dir, "index.html")
    try:
        with open(index_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"""
        <html>
            <head><title>Startup Error</title></head>
            <body style="background:#0a0813; color:#ff3366; font-family:sans-serif; padding:50px; text-align:center;">
                <h2>Generator Initialization Error</h2>
                <p>Could not locate index.html in frontend folder at absolute path:</p>
                <code style="background:#1c172d; padding:10px 20px; border-radius:6px; color:#f3f1f9;">{index_path}</code>
                <p>Details: {str(e)}</p>
            </body>
        </html>
        """

@app.get("/index.css")
def frontend_css():
    return FileResponse(os.path.join(frontend_dir, "index.css"), media_type="text/css")

@app.get("/index.js")
def frontend_js():
    return FileResponse(os.path.join(frontend_dir, "index.js"), media_type="application/javascript")

@app.get("/health")
def health():
    return {"status": "all ok"}

@app.get("/favicon.ico")
def favicon():
    # Return 204 No Content to suppress 404 errors
    return Response(status_code=204)

app.include_router(generate_router, prefix="/api")
