"""A HTTP Server to Manage Multi Rasa Model

GET /model/<name> - model info
POST /model/<name> - communicate to Rasa HTTP API
PUT /model/<name> - put(replace) file and update(train) model
PATCH /model/<name> - update file and update model

"""

__author__ = "zicong xie"
__email__ = "zicongx@foxmail.com"

from rama.utils import Result
from rama.model import get_model, Model, get_models

from sanic import Sanic, Request, HTTPResponse
from sanic.log import logger

import asyncio
from aiohttp import ClientSession

app: Sanic = Sanic("rama")


@app.before_server_start
def on_start(app: Sanic, loop):
    app.ctx.client = ClientSession(loop=loop)  # HTTP Client
    app.ctx.running_models = set()


@app.get("/")
async def index(r: Request):
    return Result().resp


@app.get("/model/<name:str>")
async def get_model_info(r: Request, name: str) -> HTTPResponse:
    """Get model info"""
    if name not in r.app.ctx.running_models:
        return Result("model_not_running", False, f"Model <{name}> is not running").resp
    return Result("model_info", True, f"Model <{name}> is running").resp


def setup_model(r: Request, name: str, force_train=False) -> HTTPResponse:
    task_name = f"setup_model_{name}"
    r.app.purge_tasks()
    task = r.app.get_task(task_name, raise_exception=False)
    if task and not task.done():
        return Result("setup_is_doing", False, f"Please wait...").resp
    r.app.add_task(get_model(name).setup(), name=task_name)
    return Result("model_traning", True, "Model start traning").resp



@app.put("/model/<name:str>")
async def put_model(r: Request, name: str):
    """Replace config and update model"""
    return setup_model(r, name, force_train=True)


def setup_all_models():
    for model in get_models():
        app.add_task(model.setup())

setup_all_models()

async def check_running_models(app: Sanic):
    """Task to gather all running models every 30 seconds"""
    await asyncio.sleep(1) # wait for setup_all_models
    while True:
        result = await asyncio.gather(*[m.is_running(app.ctx.client) for m in get_models()])
        app.ctx.running_models = set(r for r in result if result)
        await asyncio.sleep(30)

app.add_task(check_running_models(app))

if __name__ == '__main__':
    app.run(host="127.0.0.1", port=5000, debug=True, auto_reload=True)
