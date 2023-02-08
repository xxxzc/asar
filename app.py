"""A HTTP Server to Manage Multi Rasa Model

GET /model/<name> - model info
POST /model/<name> - communicate to Rasa HTTP API
PUT /model/<name> - put(replace) file and update(train) model
PATCH /model/<name> - update file and update(train) model
"""

__author__ = "zicong xie"
__email__ = "zicongx@foxmail.com"

from sanic import Sanic, response, Request, HTTPResponse
from sanic.response import json as json_resp
from sanic.views import HTTPMethodView
from subprocess import check_output, STDOUT
from functools import wraps
from pathlib import Path
import utils


def sh(*args):
    return check_output(args, stderr=STDOUT).decode("utf-8")


app: Sanic = Sanic("rama")


def ret(success=True, text="success", custom={}):
    custom["success"] = success
    return json_resp({"text": text, "custom": custom})


def check():
    def decorator(f):
        @wraps(f)
        async def decorated_function(r: Request, name: str, *args, **kwargs):
            path = utils.MODEL_DIR / name
            r.ctx.name = name
            r.ctx.path = path

            if not path.exists():
                return ret(False, f"Model {name} is not initialized yet!")

            response = await f(r, *args, **kwargs)
            return response
        return decorated_function
    return decorator


@app.get("/model/<name:str>")
@check()
async def get_model(r: Request) -> HTTPResponse:
    """Get model info"""
    return json_resp({"path": r.ctx.path.name})


@app.post("/model/<name:str>")
@check()
async def post_model(r: Request) -> HTTPResponse:
    """Communicate with Rasa Model HTTP API"""
    return json_resp({})


@app.put("/model/<name:str>")
@check()
async def put_model(r: Request) -> HTTPResponse:
    """Put/Replace file content stored in json body { path: content }

    key is file path, value is file content(string or json)

    if key is endswith 'yml', json value will be converted to yaml format
    """
    return json_resp({})


@app.patch("/model/<name:str>")
@check()
async def patch_model(r: Request) -> HTTPResponse:
    """Update file content stored in json body { path: content }
    """
    return json_resp({})


if __name__ == '__main__':
    app.run(host="127.0.0.1", port=9900, dev=True)
