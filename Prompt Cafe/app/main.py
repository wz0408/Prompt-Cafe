import mimetypes
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.core.bootstrap import init_admin
from app.api.dependencies import auth_context_middleware
from app.api.routes import ai, auth, community, prompt_version, user, prompt, admin
from app.db.database import Base, engine


Base.metadata.create_all(bind=engine)
DIST_DIR = Path(__file__).resolve().parent.parent / "dist"
FRONTEND_RESERVED_PREFIXES = ("api", "docs", "redoc", "openapi.json")
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("application/javascript", ".mjs")

app = FastAPI(
    title="Prompt Hub API",
    description="Backend API for Prompt Hub built with FastAPI",
    version="1.0.0",
)

@app.on_event("startup")
def startup_event():
    init_admin()


def _translate_validation_message(message: str) -> str:
    lower = message.lower()
    if "string should have at least 6 characters" in lower:
        return "\u5BC6\u7801\u81F3\u5C11\u9700\u8981 6 \u4F4D"
    if "string should have at least 3 characters" in lower:
        return "\u7528\u6237\u540D\u81F3\u5C11\u9700\u8981 3 \u4F4D"
    if "invalid email format" in lower:
        return "\u90AE\u7BB1\u683C\u5F0F\u4E0D\u6B63\u786E"
    if "field required" in lower:
        return "\u7F3A\u5C11\u5FC5\u586B\u5B57\u6BB5"
    return message


def _format_field_name(field: str) -> str:
    field_map = {
        "username": "\u7528\u6237\u540D",
        "email": "\u90AE\u7BB1",
        "password": "\u5BC6\u7801",
        "account": "\u8D26\u53F7",
        "nickname": "\u6635\u79F0",
        "body": "",
    }
    return field_map.get(field, field)


def _format_validation_detail(exc: RequestValidationError) -> str:
    errors = exc.errors()
    if not errors:
        return "\u8BF7\u6C42\u53C2\u6570\u4E0D\u5408\u6CD5"

    first_error = errors[0]
    message = _translate_validation_message(str(first_error.get("msg", "\u8BF7\u6C42\u53C2\u6570\u4E0D\u5408\u6CD5")))
    location = first_error.get("loc") or []
    field = next((str(item) for item in location if str(item) != "body"), "")
    field_label = _format_field_name(field) if field else ""
    return f"{field_label}\uFF1A{message}" if field_label else message


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={
            "code": 422,
            "message": "error",
            "detail": _format_validation_detail(exc),
        },
    )


app.middleware("http")(auth_context_middleware)

app.include_router(
    auth.router,
    prefix="/api/auth",
    tags=["Auth"],
)

app.include_router(
    user.router,
    prefix="/api/users",
    tags=["Users"],
)

app.include_router(
    prompt_version.router,
    prefix="/api/prompts",
    tags=["Prompt Versions"],
)

app.include_router(
    prompt.router,
    prefix="/api/prompts",
    tags=["Prompt Management"],
)

app.include_router(
    admin.router,
    prefix="/api/admin",
    tags=["Admin"],
)

app.include_router(
    community.router,
    prefix="/api/community",
    tags=["Community"],
)

app.include_router(
    ai.router,
    prefix="/api/ai",
    tags=["AI Features"],
)

if (DIST_DIR / "assets").exists():
    app.mount("/assets", StaticFiles(directory=DIST_DIR / "assets"), name="assets")

@app.get("/", tags=["General"])
def read_root():
    if DIST_DIR.joinpath("index.html").exists():
        return FileResponse(DIST_DIR / "index.html")
    return {"message": "Welcome to Prompt Hub API. Visit /docs for Swagger UI."}


@app.get("/{full_path:path}", include_in_schema=False)
def serve_frontend(full_path: str):
    if not DIST_DIR.exists():
        raise HTTPException(status_code=404, detail="Frontend build not found")

    if full_path.startswith(FRONTEND_RESERVED_PREFIXES):
        raise HTTPException(status_code=404, detail="Not found")

    requested_file = DIST_DIR / full_path
    if requested_file.is_file():
        return FileResponse(requested_file)

    index_file = DIST_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)

    raise HTTPException(status_code=404, detail="Frontend file not found")
