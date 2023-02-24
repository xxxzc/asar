import asyncio
from functools import cached_property, lru_cache
from os import cpu_count
from datetime import datetime
from pathlib import Path
from shutil import copyfile, rmtree
from typing import Optional, Union
from xmlrpc.client import ServerProxy
import filecmp

from aiohttp import ClientSession
from sanic.log import logger
from sanic.response import json as json_resp
from supervisor.rpcinterface import SupervisorNamespaceRPCInterface
from ruamel.yaml import YAML
import ujson as json

yaml = YAML(typ='safe')

# http://supervisord.org/api.html#xml-rpc-api-documentation
svctl: SupervisorNamespaceRPCInterface = ServerProxy(  # type: ignore
    'http://localhost:9999/RPC2').supervisor


CONF_VERSION = '1.0'

ROOT = Path(__file__).parent
DATA_DIR = ROOT.parent / 'data'
MODEL_DIR = DATA_DIR / 'model'
if not MODEL_DIR.exists():
    MODEL_DIR.mkdir(exist_ok=True, parents=True)

class ModelStatus:
    Stopped = "STOPPED"
    Starting = "STARTING"
    Training = "TRAINING"
    Replacing = "REPLACING"
    Running = "RUNNING"

    def __init__(self, name: str) -> None:
        self.name = name
        self.text = ModelStatus.Stopped
        self.msg = ""
        self.is_running = False
        self.model = ""
        self.status_time = datetime.now()


    @property
    def message(self):
        run_status = ModelStatus.Running if self.is_running else ModelStatus.Stopped
        run_status = "" if run_status == self.text else f" [{run_status}]"
        return f"Model {self.name}{run_status} [{self.text}] {self.msg}"

    
    def asdict(self):
        return dict(name=self.name, status=self.text, msg=self.msg,
            is_running=self.is_running, message=self.message, 
            model=self.model,
            status_time=self.status_time.isoformat())


    def resp(self):
        return json_resp(self.asdict())

    
    def set(self, text: str, msg: str, log=True):
        self.text = text
        self.msg = msg
        self.status_time = datetime.now()
        if log: logger.info(self.message)
        return self


class Program:
    """Rasa Program"""

    def __init__(self, name: str, port: int=0) -> None:
        self.name: str = f"model_{name}"
        self.port: int = port
        if port: self.name += f"_{port}"


    def url(self, path: str) -> str:
        return f"http://localhost:{self.port}/{path}"


    def is_running(self) -> bool:
        process = svctl.getProcessInfo(self.name)
        if process['state'] == 20:
            return True
        return False

    
    async def restart(self, force=True):
        if force or not self.is_running():
            restart_process = await asyncio.create_subprocess_exec(
                "supervisorctl", "restart", self.name, cwd=ROOT)
            await restart_process.wait()


    async def stop(self) -> str:
        stop_process = await asyncio.create_subprocess_exec(
            "supervisorctl", "stop", self.name, cwd=ROOT)
        await stop_process.wait()


    async def current_model(self) -> str:
        """Get current model"""
        if not self.is_running(): return ""
        status, result = await self.endpoint("get", "status")
        if status == 200:
            return result.get("model_file", "").split("/")[-1]
        return ""


    async def endpoint(self, method="get", path: str="", **kwargs) -> tuple[int, dict]:
        """Communicate to Rasa endpoint
        https://rasa.com/docs/rasa/pages/http-api

        Args:
            method: HTTPMethod
            path: Rasa HTTP API Path
            **kwargs: e.g. json={}
                see https://docs.aiohttp.org/en/stable/client.html
        """
        try:
            async with ClientSession() as client:
                http_method = getattr(client, method.lower())
                if not http_method: return 400, {"error": f"HTTP method {http_method} is not valid." }
                async with http_method(self.url(path), **kwargs) as resp:
                    result = {}
                    if resp.content_type == "application/json":
                        result = await resp.json()
                    return resp.status, result
        except Exception as e:
            logger.debug(e)
            return 500, {"error": str(e), "is_success": False }



class Model:
    """Rasa Model

    use get_model to get model instance
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self.dir = MODEL_DIR / name
        self.path("", mkdir=True)

        self.program1 = Program(self.name, self.port)
        self.program2 = Program(self.name, self.port+1)
        self.train_program = Program(f"{self.name}_tranining")
        self.current_program: Program = self.program1
        self.put_supervisor_conf()

        self.status = ModelStatus(self.name)



    async def check(self) -> ModelStatus:
        status = self.status

        model1 = await self.program1.current_model()
        model2 = await self.program2.current_model()

        if model1 != model2:
            self.current_program = self.program1 if model1 > model2 else self.program2
        
        status.model = model1 if self.current_program == self.program1 else model2
        status.is_running = len(status.model) > 0

        # training?
        if self.train_program.is_running():
            return status.set(ModelStatus.Training, "Training...")
        if not self.latest():
            await self.train()
            await asyncio.sleep(1)
            return status.set(ModelStatus.Training, "No valid model found, starting to train one")

        # running?
        if not status.model:
            await self.current_program.restart(force=False)
            await asyncio.sleep(1)
            return status.set(ModelStatus.Starting, "Model is not running, starting...")

        # replacing?
        if self.program1.is_running() and self.program2.is_running(): 
            # two programs are running --> replacing
            if model1 and model2: # all are running, stop old
                stop_program = self.program1 if self.current_program == self.program2 else self.program2
                await stop_program.stop()
                await asyncio.sleep(1)
            return status.set(ModelStatus.Replacing, "Replacing model...")

        # latest?
        status.model = await self.current_program.current_model()
        if status.model != self.latest(): # Running model is not latest -- replacing
            restart_program = self.program1 if self.current_program == self.program2 else self.program2
            await restart_program.restart(force=True)
            await asyncio.sleep(1)
            return status.set(ModelStatus.Replacing, "Current model is not latest, replacing...")

        return status.set(ModelStatus.Running, f"Current model: {status.model}, current port: {self.current_program.port}")
        

    async def train(self, data: dict={}) -> ModelStatus:
        """Train model, will stop previous training process if exists"""
        self.status.set(ModelStatus.Training, "Updating data")

        self.path("models", mkdir=True)

        if 'config.yml' in data:
            config = data['config.yml']
            if isinstance(config, str):
                config = yaml.load(config)
            if 'pipeline' in config and isinstance(config['pipeline'], list):
                for pipe in config['pipeline']:
                    for key, value in pipe.items():
                        if isinstance(value, str) and value.startswith('.'):
                            pipe[key] = self.path(value).as_posix()

        # put content to file in data
        for file, content in data.items():
            self.put(file, content)

        # check yml
        for yml in ["config.yml", "credentials.yml", "domain.yml", "endpoints.yml",
            "data/nlu.yml", "data/rules.yml", "data/stories.yml"]:
            if not self.path(yml).exists():
                copyfile(ROOT / 'sample' / yml, self.path(yml))

        await asyncio.sleep(1)
        await self.train_program.restart()
        return self.status.set(ModelStatus.Training, "Training...")

    
    def latest(self) -> Optional[str]:
        """Latest trained model name and remove old models"""
        models = list(self.path("models", mkdir=True).glob("*.tar.gz"))
        if len(models) == 0: return None

        models.sort(key=lambda x: x.stat().st_ctime, reverse=True)
        for model in models[2:]: # remove old
            model.unlink(missing_ok=True)

        return models[0].name

    
    def path(self, sub: str="", mkdir=False, rm=False) -> Path:
        """Get path in model dir
        
        Args:
            mkdir: mkdir this path
            rm: remove this path
        """
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
        tmp = Path('/tmp') / self.name / path
        tmp.parent.mkdir(exist_ok=True, parents=True)
        with open(tmp, 'w') as f:
            if isinstance(obj, str):
                f.write(obj)
            elif path.suffix == '.yml':
                yaml.dump(obj, f)
            elif path.suffix == '.json':
                json.dump(obj, f)
        
        if not filecmp.cmp(path, tmp, False): # file content is different
            tmp.rename(path)
            return True
        return False



    @cached_property
    def port(self):
        """Get server port of model"""
        ports = [int(p.name[5:]) for p in self.dir.glob("port_*")]
        if len(ports) == 0:
            used_ports = set([int(p.name[5:]) for p in MODEL_DIR.glob("*/port_*")])
            for i in range(6000, 7000, 2):
                if i not in used_ports:
                    ports = [i]
                    break
        port = ports[0]
        self.path(f"port_{port}").touch()
        return port


    async def endpoint(self, method="get", path: str="", **kwargs) -> tuple[int, dict]:
        return await self.current_program.endpoint(method, path, **kwargs)


    def put_supervisor_conf(self):
        train_command = self.path("train.sh")
        if not train_command.exists():
            self.put(train_command.name, "\n".join(
                [f"rasa train --num-threads {(cpu_count() or 6)-2}",
                 f"curl http://localhost:5000/model/{self.name}?signal=use_latest", ""]))

        supervisor_conf = self.path(f"supervisor-{CONF_VERSION}.conf")
        if not supervisor_conf.exists():
            self.put(supervisor_conf.name, "\n".join([
                f"[program:{self.program1.name}]",
                f"command=rasa run -p {self.program1.port} --cors * --enable-api --log-file run.log",
                f"directory={self.dir.as_posix()}",
                "redirect_stderr=true",
                "autostart=false",
                "autorestart=false",
                "",
                f"[program:{self.program2.name}]",
                f"command=rasa run -p {self.program2.port} --cors * --enable-api --log-file run.log",
                f"directory={self.dir.as_posix()}",
                "redirect_stderr=true",
                "autostart=false",
                "autorestart=false",
                "",
                f"[program:{self.train_program.name}]",
                f"command=sh train.sh",
                f"directory={self.dir.as_posix()}",
                "autostart=false",
                "autorestart=false",
                "redirect_stderr=true",
                ""
            ]))


    @staticmethod
    @lru_cache(maxsize=None)
    def get_model(name: str) -> "Model":
        return Model(name)


    @staticmethod
    def get_all_models() -> list["Model"]:
        """Get all models in model dir"""
        return [Model.get_model(r.name) for r in MODEL_DIR.iterdir()]
