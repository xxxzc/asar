"""A HTTP Server to Manage Multi Rasa Model

GET /model/<name> - model info
POST /model/<name> - communicate to Rasa HTTP API
PUT /model/<name> - put(replace) file and update(train) model
PATCH /model/<name> - update file and update model

"""

__author__ = "zicong xie"
__email__ = "zicongx@foxmail.com"

from rama import utils
from rama.utils import Result

from functools import wraps
from pathlib import Path
from subprocess import check_output, STDOUT
from collections import defaultdict

from rasa.model import get_latest_model

from sanic import Sanic, response, Request, HTTPResponse
from sanic.response import json as json_resp
from sanic.log import logger

import asyncio
from aiohttp import ClientSession

from xmlrpc.client import ServerProxy
from supervisor.rpcinterface import SupervisorNamespaceRPCInterface
# http://supervisord.org/api.html#xml-rpc-api-documentation
svctl: SupervisorNamespaceRPCInterface = ServerProxy(  # type: ignore
    'http://localhost:9999/RPC2').supervisor


ROOT = Path(__file__).parent
DATA_DIR = ROOT.parent / 'data'
MODEL_DIR = DATA_DIR / 'model'


app: Sanic = Sanic("rama")


@app.before_server_start
def on_start(app: Sanic, loop):
    app.ctx.client = ClientSession(loop=loop)  # HTTP Client
    app.ctx.running_models = {}


@app.get("/")
async def index(r: Request):
    return Result().resp


def full_path(path: Path):
    return path.absolute().as_posix()


async def setup_model(model_name: str, force_train=False):
    model_dir = MODEL_DIR / model_name
    # check model dir
    if not model_dir.exists():
        logger.info(f"Model dir {model_dir} not exists, init it...")
        model_dir.mkdir(exist_ok=True, parents=True)
        process = await asyncio.create_subprocess_exec("rasa", "init",
                                                       "--no-prompt",
                                                       cwd=full_path(model_dir))
        await process.wait()
        logger.info(f"Model dir {model_dir} inited.")

    # check trained model
    logger.info(f"Check for model {model_name}")
    models_dir = model_dir / 'models'
    if not models_dir.exists():
        models_dir.mkdir(exist_ok=True, parents=True)
    need_train = False
    if not get_latest_model(full_path(models_dir)):
        logger.info("No trained model exists.")
        need_train = True
    if force_train:
        logger.info("Force to train.")
        need_train = True
    if need_train:  # train one
        logger.info("Traning, please wait...")
        process = await asyncio.create_subprocess_exec("rasa", "train",
                                                       "--num-threads", "8",
                                                       cwd=full_path(model_dir))
        await process.wait()

    # use supervisor to run model
    # find new port
    ports = [int(p.name[5:]) for p in model_dir.glob("port_*")]
    if len(ports) == 0:
        used_ports = set([int(p.name[5:]) for p in MODEL_DIR.glob("*/port_*")])
        for i in range(6000, 7000):
            if i not in used_ports:
                ports = [i]
                break
    port = ports[0]
    (model_dir / f"port_{port}").touch(exist_ok=True)

    svc_file = model_dir / "supervisor.conf"
    if not svc_file.exists():
        with open(svc_file, "w") as f:
            f.write("\n".join([
                f"[program:{model_name}]",
                f"command=rasa run -p {port} --cors * --enable-api",
                f"directory={full_path(model_dir)}"
            ]))

    need_run = False
    try:
        info = svctl.getProcessInfo(model_name)
        if info['state'] != 20:
            need_run = True
    except:
        logger.error("No running model exists")
        need_run = True

    if need_run:
        pass

    # call Rasa HTTP API to replace model
    # https://rasa.com/docs/rasa/pages/http-api#operation/replaceModel
    latest_model_path = get_latest_model(full_path(models_dir))


@app.put("/model/<name:str>")
async def put_model(r: Request, name: str):
    """Put/Replace config and update
    and add model if not exists
    """
    task_name = f"setup_model_{name}"
    task = r.app.get_task(task_name, raise_exception=False)
    if task and not task.done():
        return Result("model_traning", True, f"Model {name} already in traning, please wait...").resp
    r.app.add_task(setup_model(name), name=task_name)
    return Result("model_traning", True, "Model start traning").resp


async def check_model_status(app: Sanic):
    """Update model status every 10 minutes"""
    while True:
        await asyncio.sleep(10)
        async with app.ctx.client.get("http://127.0.0.1:5000/model/dos") as resp:
            print(await resp.json(), flush=True)


async def task_running_models(app: Sanic):
    """Task to get all running models

    name: model_name_port_timestamp
    """
    while True:
        await asyncio.sleep(3)
        for process in svctl.getAllProcessInfo():
            name: str = process["name"]
            if not name.startswith("model_"):
                continue
            logger.info(process)


# app.add_task(task_running_models(app))

if __name__ == '__main__':
    app.run(host="127.0.0.1", port=5000, debug=True, auto_reload=True)
