from rama import utils
from rama.utils import Result
from pathlib import Path
from functools import cached_property
import asyncio
from typing import Optional, Union
from shutil import rmtree, copyfile
from os import cpu_count

from sanic import Sanic
from sanic.log import logger

from aiohttp import ClientSession, ClientResponse
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
    Wait = "model_waiting"
    Starting = "model_starting"
    Training = "model_training"
    Running = "model_running"
    Error = "model_error"


class Model:
    """Rasa Model

    use get_model to get model instance
    """

    def __init__(self, name: str, client: ClientSession) -> None:
        self.name = name
        self.program = f"model_{name}"
        self.train_program = f"{self.program}_training"
        self.dir = MODEL_DIR / name
        self.status = Result(ModelStatus.Wait)
        self.client = client


    def log(self, text: str, msg: str="", *args, **kwargs) -> Result:
        self.status = Result(text, f"<{self.name}> {msg}", 'error' not in msg)
        return self.status.log(*args, **kwargs)


    async def run(self, data: dict={}):
        """Run latest model with data"""

        # check models dir
        self.get_path("models", mkdir=True)

        # check supervisor.conf
        conf = self.get_path("supervisor.conf")
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

        if not self.latest_local() or data: # restart train program if no trained model
            self.log(ModelStatus.Training, "Start training...")
            
            for file, content in data.items():
                self.put(file, content)

            # check yml
            for yml in ["config.yml", "credentials.yml", "domain.yml", "endpoints.yml",
                "data/nlu.yml", "data/rules.yml", "data/stories.yml"]:
                if not self.get_path(yml).exists():
                    copyfile(ROOT / 'sample' / yml, self.get_path(yml))

            config = utils.yaml_load(self.get_path("config.yml"))
            if 'pipeline' in config and isinstance(config['pipeline'], list):
                for pipe in config['pipeline']:
                    for key, value in pipe.items():
                        # to absolute path
                        if isinstance(value, str) and value.startswith('.'):
                            pipe[key] = full_path(self.get_path(value))
            utils.yaml_dump(config, self.get_path("config.yml")) 

            restart_process = await asyncio.create_subprocess_exec(
                "supervisorctl", "restart", self.train_program, cwd=ROOT)
            await restart_process.wait()
            await asyncio.sleep(30)

        # wait for trained model
        seconds, step = 30, 15
        latest_model = self.latest_local()
        while not latest_model:
            self.log(ModelStatus.Training, f"Waiting for trained model...{seconds} seconds")
            await asyncio.sleep(step)
            seconds += step
            latest_model = self.latest_local()
        
        info = svctl.getProcessInfo(self.program)
        if info['state'] != 20:
            self.log(ModelStatus.Starting, "Model stopped, restarting...")
            restart_process = await asyncio.create_subprocess_exec(
                "supervisorctl", "restart", self.program, cwd=ROOT)
            await restart_process.wait()

        seconds, step = 0, 5

        current_model: Optional[str] = None
        while True: # wait for model to started
            try:
                self.log(ModelStatus.Starting, f"Try to connect to model...{seconds} seconds")
                status, result = await self.http_get("status")
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

            self.log(ModelStatus.Starting, "Current running model is not latest, replacing...")
            status, result = await self.http_put("model", {
                "model_file": f"models/{latest_model}"
            })
            if status == 204:
                logger.debug("Model replaced!")
            else:
                self.log(ModelStatus.Error, f"Model replacement failed: {result}")

        return self.log(ModelStatus.Running, f"Model is running, current model: {await self.current_running()}")

    
    def latest_local(self) -> Optional[str]:
        """Latest trained model name"""
        latest = get_latest_model(full_path(self.get_path("models")))
        if not latest: return None
        return latest.split('/')[-1]


    async def current_running(self) -> Optional[str]:
        status, result = await self.http_get("status")
        if status == 200:
            return result.get("model_file", "").split("/")[-1]
        return None


    def rm(self, path):
        """Remove file or directory in model dir"""
        path = self.get_path(path)
        if not path.exists(): return
        if path.is_dir():
            rmtree(path)
        else:
            path.unlink(missing_ok=True)


    def put(self, path, obj: Union[str, dict]):
        """Put obj to path
        
        Args:
            path: relative path to model dir
            obj: 
                - str: write to path
                - dict: store yml if path is yml then json
        """
        path = self.get_path(path)
        with open(path, 'w') as f:
            if isinstance(obj, str):
                f.write(obj)
            elif path.suffix == '.yml':
                utils.yaml.dump(obj, f)
            else:
                utils.json.dump(obj, f)

    
    def get_path(self, sub: str="", mkdir=False) -> Path:
        path = self.dir
        if sub: path = path / sub
        if mkdir and not path.exists():
            path.mkdir(exist_ok=True, parents=True)
        if not path.parent.exists():
            path.parent.mkdir(exist_ok=True, parents=True)
        return path


    @cached_property
    def port(self):
        """Get port of model"""
        ports = [int(p.name[5:]) for p in self.dir.glob("port_*")]
        if len(ports) == 0:
            used_ports = set([int(p.name[5:]) for p in MODEL_DIR.glob("*/port_*")])
            for i in range(6000, 7000):
                if i not in used_ports:
                    ports = [i]
                    break
        port = ports[0]
        self.get_path(f"port_{port}").touch()
        return port


    def get_url(self, path: str):
        return f"http://localhost:{self.port}/{path}"


    async def http_get(self, path: str, data: dict={}) -> tuple[int, dict]:
        try:
            async with self.client.get(self.get_url(path), params=data) as resp:
                result = {}
                if resp.content_type == "application/json":
                    result = await resp.json()
                return resp.status, result
        except Exception as e:
            logger.debug(e)
            return 500, {"error": str(e)}

    
    async def http_post(self, path: str, data={}) -> tuple[int, dict]:
        try:
            async with self.client.post(self.get_url(path), json=data) as resp:
                result = {}
                if resp.content_type == "application/json":
                    result = await resp.json()
                return resp.status, result
        except Exception as e:
            logger.debug(e)
            return 500, {"error": str(e)}

    
    async def http_put(self, path: str, data={}) -> tuple[int, dict]:
        try:
            async with self.client.put(self.get_url(path), json=data) as resp:
                result = {}
                if resp.content_type == "application/json":
                    result = await resp.json()
                return resp.status, result
        except Exception as e:
            logger.debug(e)
            return 500, {"error": str(e)}


    async def http(self, path: str="webhooks/rest/webhook", data={}, method="POST") -> tuple[int, dict]:
        http_method = self.http_post
        if method == 'GET':
            http_method = self.http_get
        elif method == "PUT":
            http_method = self.http_put
        return await http_method(path, data)



def get_models() -> list[str]:
    return [m.name for m in MODEL_DIR.iterdir()]