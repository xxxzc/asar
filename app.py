"""A HTTP Server to Manage Multi Rasa Model

GET /model/<name> - model info
POST /model/<name> - communicate to Rasa HTTP API
PUT /model/<name> - put(replace) file and update(train) model
PATCH /model/<name> - update file and update model

We assumed that when this server started, all defined(defined in visor/) model
will be started by supervisor, 
but we should use a timed task to check if each model is avaliable

I will use following assumed scenario to implement this server:
Initially, no model runs, user get model/name, it should notice not initialized
Then, use put model/name to init 
"""

__author__ = "zicong xie"
__email__ = "zicongx@foxmail.com"

from rama import utils
from rama.model import Model

from functools import wraps
from pathlib import Path
from subprocess import check_output, STDOUT
from collections import defaultdict

from sanic import Sanic, response, Request, HTTPResponse
from sanic.response import json as json_resp
from sanic.views import HTTPMethodView
from sanic.log import logger

import asyncio
from aiohttp import ClientSession

from xmlrpc.client import ServerProxy
from supervisor.rpcinterface import SupervisorNamespaceRPCInterface


# http://supervisord.org/api.html#xml-rpc-api-documentation
svctl: SupervisorNamespaceRPCInterface = ServerProxy( # type: ignore
    'http://localhost:9999/RPC2').supervisor

app: Sanic = Sanic("rama")


@app.before_server_start
def on_start(app: Sanic, loop):
    app.ctx.client = ClientSession(loop=loop) # HTTP Client
    app.ctx.running_models = {}


def fill_ctx(f):
    @wraps(f)
    async def wrap(r: Request, name: str, *args, **kwargs):
        path = utils.MODEL_DIR / name
        r.ctx.name = name
        r.ctx.path = path
        return await f(r, *args, **kwargs)
    return wrap


def check():
    def decorator(f):
        @wraps(f)
        async def decorated_function(r: Request, *args, **kwargs):
            logger.info(r.ctx.path)
            if not r.ctx.path.exists():
                return utils.Result("model_not_exist", False, f"Model {r.ctx.name} is not initialized yet!").resp
            response = await f(r, *args, **kwargs)
            return response
        return decorated_function
    return decorator


@app.get("/model/<name:str>")
@fill_ctx
@check()
async def get_model(r: Request) -> HTTPResponse:
    """Get model info"""
    return json_resp({"path": r.app.ctx.k})


@app.post("/model/<name:str>")
@fill_ctx
@check()
async def post_model(r: Request) -> HTTPResponse:
    """Communicate with Rasa Model HTTP API"""
    return json_resp({})


@app.put("/model/<name:str>")
@fill_ctx
async def put_model(r: Request) -> HTTPResponse:
    """Put/Replace file content stored in json body { path: content }

    key is file path, value is file content(string or json)
    specially, if key is endswith 'yml', json value will be converted to yaml format
    """

    body: dict = r.json or {}

    return json_resp({})


@app.patch("/model/<name:str>")
@fill_ctx
@check()
async def patch_model(r: Request) -> HTTPResponse:
    """Update file content stored in json body { path: content }

    if body is empty, it will rerun model
    """
    return utils.Result("error_not_implemented", False, "This method is under development").resp



async def check_model_status(app: Sanic):
    """Update model status every 10 minutes"""
    while True:
        await asyncio.sleep(10)
        async with app.ctx.client.get("http://127.0.0.1:5000/model/dos") as resp:
                print(await resp.json(), flush=True)
  


async def discover_running_model(app: Sanic):
    """Discover running model
    
    1. In supervisor and running
    2. Server is fine
    """
    running_models = defaultdict(list)
    for program in svctl.getAllProcessInfo():
        if not program["name"].startswith("model_"):
            continue




# app.add_task(check_model_status(app))

if __name__ == '__main__':
    app.run(host="127.0.0.1", port=5000, dev=True)
