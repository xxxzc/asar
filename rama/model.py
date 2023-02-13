from rama import utils
from rama.utils import Result
from pathlib import Path
from functools import cached_property
import asyncio
from typing import Any, Callable, Optional, Union
from shutil import rmtree, copyfile
from os import cpu_count

from sanic.log import logger

from aiohttp import ClientSession
import requests

from functools import lru_cache

from xmlrpc.client import ServerProxy
from supervisor.rpcinterface import SupervisorNamespaceRPCInterface

# http://supervisord.org/api.html#xml-rpc-api-documentation
svctl: SupervisorNamespaceRPCInterface = ServerProxy(  # type: ignore
    'http://localhost:9999/RPC2').supervisor


from rasa.model import get_latest_model

ROOT = utils.ROOT
DATA_DIR = ROOT.parent / 'data'
MODEL_DIR = DATA_DIR / 'model'
if not MODEL_DIR.exists():
    MODEL_DIR.mkdir(exist_ok=True, parents=True)

def full_path(path: Path) -> str:
    return path.absolute().as_posix()


class ModelStatus:
    Waiting = "model_waiting"
    Starting = "model_starting"
    Training = "model_training"
    Running = "model_running"
    Error = "model_error"


class Model:
    """Rasa Model

    use get_model to get model instance
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self.program = f"model_{name}"
        self.train_program = f"{self.program}_training"

        self.dir = MODEL_DIR / name
        self.status = Result(ModelStatus.Waiting)
        self.is_running = False


    @staticmethod
    @lru_cache(maxsize=None)
    def get_model(name: str) -> "Model":
        return Model(name)


    def log(self, text: str, msg: str="", *args, **kwargs) -> Result:
        self.status = Result(text, f"Model <{self.name}> {msg}", 'error' not in msg)
        self.status.update_custom(running=self.is_running)
        return self.status.log(*args, **kwargs)


    async def run(self, data: dict={}, callback: Optional[Callable]=None):
        """Run latest model with data"""

        # check models dir
        self.path("models", mkdir=True)

        # check supervisor.conf
        conf = self.path("supervisor.conf")
        if not conf.exists():
            with open(conf, "w") as f:
                f.write("\n".join([
                    f"[program:{self.program}]",
                    f"command=rasa run -p {self.port} --cors * --enable-api --log-file run.log",
                    f"directory={full_path(self.dir)}",
                    "redirect_stderr=true",
                    "",
                    f"[program:{self.train_program}]",
                    f"command=rasa train --num-threads {(cpu_count() or 6)-2}",
                    f"directory={full_path(self.dir)}",
                    "autostart=false",
                    "autorestart=false",
                    "redirect_stderr=true"
                ]))

            update_process = await asyncio.create_subprocess_exec(
                "supervisorctl", "update", cwd=ROOT)
            await update_process.wait()

        if not self.latest() or data: # restart train program if no trained model
            self.log(ModelStatus.Training, "Start training...")
            
            for file, content in data.items():
                self.put(file, content)

            # check yml
            for yml in ["config.yml", "credentials.yml", "domain.yml", "endpoints.yml",
                "data/nlu.yml", "data/rules.yml", "data/stories.yml"]:
                if not self.path(yml).exists():
                    copyfile(ROOT / 'sample' / yml, self.path(yml))

            config = utils.yaml_load(self.path("config.yml"))
            if 'pipeline' in config and isinstance(config['pipeline'], list):
                for pipe in config['pipeline']:
                    for key, value in pipe.items():
                        # to absolute path
                        if isinstance(value, str) and value.startswith('.'):
                            pipe[key] = full_path(self.path(value))
            utils.yaml_dump(config, self.path("config.yml")) 

            restart_process = await asyncio.create_subprocess_exec(
                "supervisorctl", "restart", self.train_program, cwd=ROOT)
            await restart_process.wait()
            await asyncio.sleep(30)

        # wait for model to be trained
        seconds, step = 30, 15
        latest_model = self.latest()
        while not latest_model:
            self.log(ModelStatus.Training, f"Waiting for model to be trained...{seconds} seconds")
            await asyncio.sleep(step)
            seconds += step
            latest_model = self.latest()
        
        info = svctl.getProcessInfo(self.program)
        if info['state'] != 20:
            self.log(ModelStatus.Starting, "is stopped, restarting...")
            restart_process = await asyncio.create_subprocess_exec(
                "supervisorctl", "restart", self.program, cwd=ROOT)
            await restart_process.wait()

        seconds, step = 0, 5

        current_model: Optional[str] = None
        while True: # wait for model to started
            try:
                self.log(ModelStatus.Starting, f"Waiting for model to start...{seconds} seconds")
                status, result = await self.http("get", "status")
                if status == 200:
                    current_model = result.get("model_file", "").split("/")[-1]
                    break
                elif status == 409:
                    break
            except: pass

            await asyncio.sleep(step)
            seconds += step

        # use latest model
        if not current_model or current_model != latest_model:
            # Call Rasa to replace model
            # this method will make model down a while
            # https://rasa.com/docs/rasa/pages/http-api#operation/replaceModel

            self.log(ModelStatus.Starting, "is not latest, replacing...")
            self.is_running = False
            status, result = await self.http("put", "model", json={
                "model_file": f"models/{latest_model}"
            })
            if status == 204:
                logger.debug("Model replaced!")
            else:
                self.log(ModelStatus.Error, f"Replacement failed: {result}")

        return self.log(ModelStatus.Running, f"is running, current model: {self.current()}")

    
    def latest(self) -> Optional[str]:
        """Latest trained model name"""
        latest = get_latest_model(full_path(self.path("models")))
        if not latest: return None
        return latest.split('/')[-1]


    def current(self) -> Optional[str]:
        """Return current model name if model is running"""
        resp = requests.get(self.url("status"))
        if resp.status_code == 200:
            self.is_running = True
            return resp.json().get("model_file", "").split("/")[-1]
        self.is_running = False
        return None

    
    def path(self, sub: str="", mkdir=False, rm=False) -> Path:
        path = self.dir
        if sub: path = path / sub
        if not path.parent.exists():
            path.parent.mkdir(exist_ok=True, parents=True)

        if mkdir and not path.exists():
            path.mkdir(exist_ok=True)

        if rm and path.exists():
            if path.is_dir():
                rmtree(path)
            else:
                path.unlink(missing_ok=True)
        return path


    def put(self, path, obj: Union[str, dict]):
        """Put obj to path
        
        Args:
            path: relative path to model dir
            obj: 
                - str: write to path
                - dict: store yml if path is yml then json
        """
        path = self.path(path)
        with open(path, 'w') as f:
            if isinstance(obj, str):
                f.write(obj)
            elif path.suffix == '.yml':
                utils.yaml.dump(obj, f)
            else:
                utils.json.dump(obj, f)


    @cached_property
    def port(self):
        """Get server port of model"""
        ports = [int(p.name[5:]) for p in self.dir.glob("port_*")]
        if len(ports) == 0:
            used_ports = set([int(p.name[5:]) for p in MODEL_DIR.glob("*/port_*")])
            for i in range(6000, 7000):
                if i not in used_ports:
                    ports = [i]
                    break
        port = ports[0]
        self.path(f"port_{port}").touch()
        return port


    def url(self, path: str):
        return f"http://localhost:{self.port}/{path}"


    async def http(self, method="get", path: str="", **kwargs) -> tuple[int, dict]:
        """Communicate to Rasa HTTP API 
        https://rasa.com/docs/rasa/pages/http-api

        Args:
            method: HTTPMethod, default post
            path: Rasa HTTP API Path, default "webhooks/rest/webhook"
            **kwargs: e.g. json={}
                see https://docs.aiohttp.org/en/stable/client.html
        """
        try:
            async with ClientSession() as client:
                http_method = getattr(client, method.lower())
                if not http_method: return 404, {"error": f"HTTP method {http_method} is not valid." }
                async with http_method(self.url(path), **kwargs) as resp:
                    result = {}
                    if resp.content_type == "application/json":
                        result = await resp.json()
                    return resp.status, result
        except Exception as e:
            logger.debug(e)
            return 500, {"error": str(e)}


    @staticmethod
    def get_all_models() -> list["Model"]:
        return [Model.get_model(r.name) for r in MODEL_DIR.iterdir()]
