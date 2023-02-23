import asyncio
from pathlib import Path

from sanic import HTTPResponse, Request, Sanic
from sanic.log import logger
from sanic.response import json as json_resp, redirect
from aiohttp import ClientSession, ClientResponse

from model import Model, ModelStatus

APP_NAME = "asar"

app: Sanic = Sanic(APP_NAME)
app.config.CORS_ORIGINS = "*"


@app.before_server_start
def before_start(app: Sanic, loop):
    app.ctx.client = ClientSession(loop=loop)


@app.route("/supervisor/<path:path>")
async def proxy_to_supervisor(r: Request, path: str) -> HTTPResponse:
    """Reverse proxy for supervisor"""
    if r.args.get("processname", "") == APP_NAME and r.args.get("action", "") == "stop":
        return redirect("/supervisor/") # do not stop this app

    method = getattr(r.app.ctx.client, r.method.lower())
    async with method("http://localhost:9999/"+path, headers=r.headers,
            params=r.args, json=r.json) as resp:
        resp: ClientResponse
        response = await r.respond(content_type=resp.content_type, 
            status=resp.status, headers=resp.headers)
        async for data in resp.content.iter_any():
            await response.send(data)
        await response.eof()
        if r.path.endswith('index.html') or r.path.endswith('/'):
            return redirect("/supervisor/")
        return response


def redirect_to_supervisor(r: Request) -> HTTPResponse:
    if r.path == "/" and r.args.get("message", None):
        return proxy_to_supervisor(r, "")
    return redirect("/supervisor/")

app.add_route(redirect_to_supervisor, "/")
app.add_route(redirect_to_supervisor, "/supervisor")


async def check_models(app: Sanic):
    while True:
        for model in Model.get_all_models():
            await model.check()
        process = await asyncio.create_subprocess_exec("supervisorctl", "update", cwd=Path(__file__).parent)
        await process.wait()
        await asyncio.sleep(60)

app.add_task(check_models)


@app.get("/model/<name:str>")
async def get_model(r: Request, name: str) -> HTTPResponse:
    """Get model status"""
    model = Model.get_model(name)
    return (await model.check()).resp()


@app.post("/model/<name:str>")
async def post_model(r: Request, name: str) -> HTTPResponse:
    """Communicate to Rasa HTTP API
    
    You should put the following in request json body
    See [Rasa HTTP API](https://rasa.com/docs/rasa/pages/http-api)

    - path: Rasa HTTP API Path
    - method: HTTP Method that path allowed
    - **kwargs: arguments passed to [AIOHTTP Client](https://docs.aiohttp.org/en/stable/client.html)
    
    POST /model/name
    {
        "method": "post", // HTTP Method
        "path": "webhooks/rest/webhook", // API Path
        "json": { "sender": "xxxzc", "message": "hello" }, // json data
    }

    Return 500 if model is not running
    """
    model = Model.get_model(name)
    if not model.status.is_running:
        return json_resp(model.status.asdict(), 400)
    j = r.json or {}
    status, result = await model.endpoint(
        j.pop("method", "post"), 
        j.pop("path", "webhooks/rest/webhook"),
        **j)
    return json_resp(result, status)


@app.put("/model/<name:str>")
async def put_model(r: Request, name: str) -> HTTPResponse:
    """Put files and update model
    
    Files are storied in request json body
    
    PUT /model/name
    {
        // raw file content - saved directly
        "config.yml": "recipe: default.v1...",
        // convert to yaml and save to domain.yml
        "domain.yml": { "version": "3.1", ... },
        // save to deeper path
        "dictionary/userdict.txt": "foobar"
    }

    After saving all files, a new model will be trained and be used.
    """
    model = Model.get_model(name)
    return (await model.train(r.json or {})).resp()

if __name__ == '__main__':    
    app.run(host="0.0.0.0", port=5000, debug=True, auto_reload=True)
