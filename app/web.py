from pathlib import Path

from aiohttp import web

from app.config import PROJECT_ROOT


def create_web_app(dist_dir: Path | None = None) -> web.Application:
    dist = dist_dir if dist_dir is not None else PROJECT_ROOT / "mini_app" / "dist"
    if not (dist / "index.html").is_file() or not (dist / "assets").is_dir():
        raise RuntimeError(
            "Mini App ещё не собрано. Выполните в папке mini_app: "
            "npm install, затем npm run build."
        )

    async def index(request: web.Request) -> web.FileResponse:
        return web.FileResponse(dist / "index.html", headers={"Cache-Control": "no-cache"})

    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_static("/assets/", dist / "assets", show_index=False)
    return app
