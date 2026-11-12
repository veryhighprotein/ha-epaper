import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote

from aiohttp import ClientSession, web
from jinja2 import Environment, FileSystemLoader, select_autoescape

HA_URL = os.environ.get("HA_URL", "").rstrip("/")
HA_TOKEN = os.environ.get("HA_TOKEN", "")
PORT = os.environ.get("PORT", "8080")
IMAGES = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}


async def client_context(app):
    async with ClientSession(
        headers={"Authorization": f"Bearer {HA_TOKEN}"}
    ) as session:
        app["ha"] = session
        yield


async def image(request):
    file = next(Path(".").glob("image.*"), None)
    if file is None:
        raise web.HTTPNotFound
    return web.FileResponse(file)


async def upload(request):
    form = await request.post()
    new = form.get("image")
    if "clear" in form:
        target = None
    else:
        suffix = Path(new.filename).suffix.lower() if new else ""
        if suffix not in IMAGES:
            raise web.HTTPBadRequest(text="no image")
        target = Path(f"image{suffix}")
    for file in Path(".").glob("image.*"):
        file.unlink()
    if target:
        target.write_bytes(new.file.read())
    return web.HTTPSeeOther("/")


async def upload_form(request):
    html = request.app["templates"].get_template("upload.html").render(
        config=request.app["config"]
    )
    return web.Response(text=html, content_type="text/html")


async def page(request):
    session = request.app["ha"]
    config = request.app["config"]
    now = datetime.now().astimezone()
    calendar_days = int(config.get("calendar_days", 7))
    forecast_days = int(config.get("forecast_days", 7))

    async with session.get(f"{HA_URL}/api/states") as response:
        response.raise_for_status()
        states = {item["entity_id"]: item for item in await response.json()}

    events = []
    for calendar in config.get("calendars", []):
        async with session.get(
            f"{HA_URL}/api/calendars/{quote(calendar, safe='')}",
            params={
                "start": now.isoformat(),
                "end": (now + timedelta(days=calendar_days)).isoformat(),
            },
        ) as response:
            response.raise_for_status()
            events += await response.json()
    events.sort(key=lambda event: event["start"].get("dateTime") or event["start"]["date"])

    forecast = []
    if weather := config.get("weather"):
        async with session.post(
            f"{HA_URL}/api/services/weather/get_forecasts?return_response",
            json={"entity_id": weather, "type": "daily"},
        ) as response:
            response.raise_for_status()
            data = await response.json()
        forecast = data["service_response"][weather]["forecast"][:forecast_days]

    html = request.app["templates"].get_template("dashboard.html").render(
        config=config,
        states=states,
        events=events,
        forecast=forecast,
        now=now,
        image_available=any(Path(".").glob("image.*")),
        refresh_seconds=int(config.get("refresh_minutes", 30)) * 60,
    )
    return web.Response(text=html, content_type="text/html")


def make_templates() -> Environment:
    env = Environment(
        loader=FileSystemLoader(Path(__file__).parent),
        autoescape=select_autoescape(["html"]),
    )
    env.filters["dayfmt"] = lambda v: datetime.fromisoformat(v).strftime("%a %d.%m")
    return env


def main() -> None:
    if not all((HA_URL, HA_TOKEN, PORT)):
        raise SystemExit("HA_URL, HA_TOKEN and PORT must be set")

    parser = argparse.ArgumentParser()
    parser.add_argument("config")
    args = parser.parse_args()

    app = web.Application()
    app["config"] = json.loads(sys.stdin.read() if args.config == "-" else Path(args.config).read_text())
    app["templates"] = make_templates()
    app.cleanup_ctx.append(client_context)
    app.router.add_get("/", page)
    app.router.add_get("/image", image)
    app.router.add_get("/upload", upload_form)
    app.router.add_post("/upload", upload)
    web.run_app(app, host="0.0.0.0", port=int(PORT))
