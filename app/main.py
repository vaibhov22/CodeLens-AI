from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.api.routes import router
from app.core.model_loader import model  # keep if needed

app = FastAPI()

# 🔥 CORS (required for frontend)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 🔗 include routes
app.include_router(router)
#{ frontend
# 🔥 serve static files (CSS, JS)
app.mount("/static", StaticFiles(directory="static"), name="static")

# 🔥 templates (HTML)
templates = Jinja2Templates(directory="templates")

# 🔥 frontend route
@app.get("/")
def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})
#}