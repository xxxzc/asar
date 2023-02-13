"""A HTTP Server to Manage Multi Rasa Model

GET /model/<name> - model info
POST /model/<name>/path?method=post - communicate to Rasa HTTP API
PUT /model/<name> - put(replace) file and update(train) model
{
    "path": str or dict, ...
}
~~PATCH /model/<name> - update file and update model~~

"""

__author__ = "zicong xie"
__email__ = "zicongx@foxmail.com"

from typing import Coroutine

from rama import utils
from rama.utils import Result
from rama.model import Model, get_models

from sanic import Sanic, Request, HTTPResponse
from sanic.response import redirect
from sanic.log import logger

import asyncio
from aiohttp import ClientSession

from rasa.server import create_app

class AppContext:
    client: ClientSession
    models: dict[str, Model]
    running_models: dict[str, Model]


app: Sanic = Sanic("rama", ctx=AppContext())
ctx: AppContext = app.ctx


@app.before_server_start
def on_start(app: Sanic, loop):
    app.ctx.client = ClientSession(loop=loop)  # HTTP Client
    app.ctx.models = {}
    app.ctx.running_models = {}


@app.get("/")
async def index(r: Request):
    return Result("index", running_models=list(ctx.running_models)).resp


@app.get("/model/<name:str>")
async def get_model(r: Request, name: str) -> HTTPResponse:
    """Get model info"""
    model = ctx.running_models.get(name, None)
    if not model:
        return Result("model_not_running", f"Model <{name}> is not running", False).resp
    return model.status.resp


# @app.post("/model/<name:str>")
# async def post_model(r: Request, name: str) -> HTTPResponse:
#     """Ask to model/webhooks/rest/webhook"""
#     return await post_rasa_model(r, name, path)

@app.post("/model/<name:str>/<path:path>")
async def post_rasa_model(r: Request, name: str, path: str) -> HTTPResponse:
    """Communicate to RASA HTTP API
    """
    model = ctx.running_models[name]
    status, result = await model.http(path, r.json or {})
    return utils.json_resp(result, status)




async def setup_model(name: str, data: dict={}):
    model = ctx.models.get(name, None)
    if not model:
        model = Model(name, ctx.client)
        ctx.models[name] = model
    await model.run(data)
    if await model.current_running():
        ctx.running_models[name] = model


def train_model(name: str, data: dict={}) -> Result:
    app.add_task(setup_model(name, data))
    return Result("model_traning", "Model start traning")


@app.put("/model/<name:str>")
async def put_model(r: Request, name: str) -> HTTPResponse:
    """Replace config and update model"""
    return train_model(name, r.json).resp # type: ignore


@app.get("supervisor")
async def supervisor_html(r: Request) -> HTTPResponse:
    return redirect("http://localhost:9999")


async def check_models(app: Sanic):
    """Check models every 30 seconds"""
    while True:
        for name in get_models():
            if name not in ctx.models:
                app.add_task(setup_model(name))
                continue
            model = ctx.models[name]
            if await model.current_running():
                ctx.running_models[name] = model
        await asyncio.sleep(30)

app.add_task(check_models(app))


async def update_supervisor():
    """Update supervisor when startup"""
    process = await asyncio.create_subprocess_exec("supervisorctl", "update", cwd=utils.ROOT)
    await process.wait()


if __name__ == '__main__':
    app.run(host="127.0.0.1", port=5000, debug=True, auto_reload=True)
