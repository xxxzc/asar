"""RAAS: A HTTP Server to Manage Multi Rasa Instance

GET /model/<name> - model info
POST /model/<name> - communicate to Rasa HTTP API
{
    "method": "post", "path": "webhooks/rest/webhook", 
    "json": {
        "sender": "xxxzc", "message": "hello"
    }
}
PUT /model/<name> - put(replace) file and update(train) model
{
    "config.yml": { ... }, "dictionary/userdict.txt": "foo/nbar/n"
}
~~PATCH /model/<name> - update file and update model~~

"""

__author__ = "zicong xie"
__email__ = "zicongx@foxmail.com"

from rama.utils import Result
from rama.model import Model, ModelStatus

import asyncio
from pathlib import Path

from sanic import Sanic, Request, HTTPResponse
from sanic.response import json as json_resp
from sanic.log import logger


app: Sanic = Sanic("rama")


@app.get("/")
async def index(r: Request) -> HTTPResponse:
    return json_resp([m.status.as_dict() for m in Model.get_all_models()])


@app.get("/model/<name:str>")
async def get_model(r: Request, name: str) -> HTTPResponse:
    """Get model info"""
    model = Model.get_model(name)
    if not model.dir.exists():
        return Result("model_not_exists", f"Model <{name}> is not exists", False).resp
    return model.status.resp


@app.post("/model/<name:str>")
async def post_model(r: Request, name: str) -> HTTPResponse:
    """Communicate to Rasa HTTP API
    https://rasa.com/docs/rasa/pages/http-api

    Args:
        method: HTTPMethod, default post
        path: Rasa HTTP API Path, default "webhooks/rest/webhook"
        **kwargs: e.g. json={}
            see https://docs.aiohttp.org/en/stable/client.html
    """
    model = Model.get_model(name)
    j = r.json or {}
    status, result = await model.http(
        j.pop("method", "post"), 
        j.pop("path", "webhooks/rest/webhook"),
        **j)
    return json_resp(result, status)


@app.put("/model/<name:str>")
async def put_model(r: Request, name: str) -> HTTPResponse:
    """Replace config and update model
    
    { "config.yml": {}, "data/stories.yml": "", ... }
    """
    model = Model.get_model(name)
    app.add_task(model.run(r.json or {}))
    return Result(ModelStatus.Training, f"Model <{name}> start training").resp


async def check_models(app: Sanic, seconds: int):
    """Check models"""
    while True:
        for model in Model.get_all_models():
            logger.info(f"Checking model <{model.name}>:")
            if not model.is_running:
                app.add_task(model.run())
            model.current()
        await asyncio.sleep(seconds)

app.add_task(check_models(app, 60))


async def update_supervisor():
    """Update supervisor at start"""
    process = await asyncio.create_subprocess_exec("supervisorctl", "update", cwd=Path(__file__).parent)
    await process.wait()

app.add_task(update_supervisor())


if __name__ == '__main__':
    
    app.run(host="127.0.0.1", port=5000, debug=True, auto_reload=True)
