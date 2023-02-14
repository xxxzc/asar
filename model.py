import asyncio
from functools import cached_property, lru_cache
from os import cpu_count
from pathlib import Path
from shutil import copyfile, rmtree
from typing import Optional, Union
from xmlrpc.client import ServerProxy

from aiohttp import ClientSession
from sanic.log import logger
from supervisor.rpcinterface import SupervisorNamespaceRPCInterface
from ruamel.yaml import YAML
import ujson as json

yaml = YAML(typ='safe')

# http://supervisord.org/api.html#xml-rpc-api-documentation
svctl: SupervisorNamespaceRPCInterface = ServerProxy(  # type: ignore
    'http://localhost:9999/RPC2').supervisor


ROOT = Path(__file__).parent
DATA_DIR = ROOT.parent / 'data'
MODEL_DIR = DATA_DIR / 'model'
if not MODEL_DIR.exists():
    MODEL_DIR.mkdir(exist_ok=True, parents=True)

def full_path(path: Path) -> str:
    return path.absolute().as_posix()


class ModelStatus:
    Waiting = "WAITING"
    Starting = "STARTING"
    Training = "TRAINING"
    Replacing = "REPLACING"
    Running = "RUNNING"
    Stopped = "STOPPED"
    Error = "ERROR"

    def __init__(self, name: str) -> None:
        self.name = name
        self.status = ModelStatus.Stopped
        self.msg = "Waiting to run"
        self.is_running = False


    @property
    def message(self):
        run_status = ModelStatus.Running if self.is_running else ModelStatus.Stopped
        run_status = "" if run_status == self.status else f" [{run_status}]"
        return f"Model <{self.name}>{run_status} [{self.status}] {self.msg}"

    
    def as_dict(self):
        return dict(name=self.name, status=self.status, msg=self.msg,
            is_running=self.is_running, message=self.message)

    
    def set(self, status: str, msg: str, log=True):
        self.status = status
        self.msg = msg
        if log: logger.info(self.message)
        return self


class Model:
    """Rasa Model

    use get_model to get model instance
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self.program = f"model_{name}"
        self.train_program = f"{self.program}_training"
        self.dir = MODEL_DIR / name
        self.status: ModelStatus = ModelStatus(name)
        

    @staticmethod
    @lru_cache(maxsize=None)
    def get_model(name: str) -> "Model":
        return Model(name)

    async def run(self, data: dict={}):
        """Check and run latest model with data"""
        await self.current() # check current status

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

            # svctl.reloadConfig just do a diff, without actually doing the update
            # so we should call update in shell
            update_process = await asyncio.create_subprocess_exec(
                "supervisorctl", "update", cwd=ROOT)
            await update_process.wait()

        if not self.latest() or data: # train
            self.status.set(ModelStatus.Training, "Training...")
            
            # put content to file in data
            for file, content in data.items():
                self.put(file, content)

            # check yml
            for yml in ["config.yml", "credentials.yml", "domain.yml", "endpoints.yml",
                "data/nlu.yml", "data/rules.yml", "data/stories.yml"]:
                if not self.path(yml).exists():
                    copyfile(ROOT / 'sample' / yml, self.path(yml))

            config_yml = self.path("config.yml")
            with open(config_yml, "r") as f:
                config = yaml.load(f)
                if 'pipeline' in config and isinstance(config['pipeline'], list):
                    for pipe in config['pipeline']:
                        for key, value in pipe.items():
                            if isinstance(value, str) and value.startswith('.'):
                                pipe[key] = full_path(self.path(value)) # to absolute path
                with open(config_yml, "w") as w:
                    yaml.dump(config, w)

            update_process = await asyncio.create_subprocess_exec(
                "supervisorctl", "update", cwd=ROOT)
            await update_process.wait()

            restart_process = await asyncio.create_subprocess_exec(
                "supervisorctl", "restart", self.train_program, cwd=ROOT)
            await restart_process.wait()
            await asyncio.sleep(30)

        # wait until model trained
        seconds, step = 30, 15
        latest_model = self.latest()
        while not latest_model:
            self.status.set(ModelStatus.Training, f"Waiting for model to be trained...{seconds} seconds")
            await asyncio.sleep(step)
            seconds += step
            latest_model = self.latest()
        
        # restart model if stopped
        info = svctl.getProcessInfo(self.program)
        if info['state'] != 20:
            self.status.set(ModelStatus.Stopped, "Restarting...")
            restart_process = await asyncio.create_subprocess_exec(
                "supervisorctl", "restart", self.program, cwd=ROOT)
            await restart_process.wait()

        # wait until model started
        seconds, step = 0, 5
        current_model: Optional[str] = None
        while True: 
            try:
                self.status.set(ModelStatus.Starting, f"Waiting for model to start...{seconds} seconds")
                status, result = await self.endpoint("get", "status")
                if status == 200:
                    current_model = result.get("model_file", "").split("/")[-1]
                    break
                elif status == 409:
                    break
            except: pass

            await asyncio.sleep(step)
            seconds += step

        # use latest model
        # There is no need to consider repeated calls, 
        # because if there is already a replacement currently in progress, 
        # we will be stuck at previous step and will not proceed here
        if not current_model or current_model != latest_model:
            # Call Rasa to replace model, this method will make model down a while(~30s)
            # https://rasa.com/docs/rasa/pages/http-api#operation/replaceModel

            self.status.set(ModelStatus.Replacing, "Running model is not latest, replacing...")
            status, result = await self.endpoint("put", "model", json={
                "model_file": f"models/{latest_model}"
            })
            if status == 204:
                logger.debug("Model replaced!")
            else:
                self.status.set(ModelStatus.Error, f"Replacement failed: {result}")

        return self.status.set(ModelStatus.Running, f"Current model: {await self.current()}")

    
    def latest(self) -> Optional[str]:
        """Latest trained model name and remove old models"""
        models = list(self.path("models", mkdir=True).glob("*.tar.gz"))
        if len(models) == 0: return None

        models.sort(key=lambda x: x.stat().st_ctime, reverse=True)
        for model in models[2:]: # remove old
            model.unlink(missing_ok=True)

        return models[0].name


    async def current(self) -> Optional[str]:
        """Return current model name if model is running and update status"""
        status, result = await self.endpoint("get", "status")
        if status == 200:
            self.status.is_running = True
            return result.get("model_file", "").split("/")[-1]
        self.status.is_running = False
        return None

    
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
        with open(path, 'w') as f:
            if isinstance(obj, str):
                f.write(obj)
            elif path.suffix == '.yml':
                yaml.dump(obj, f)
            else:
                json.dump(obj, f)


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


    async def endpoint(self, method="get", path: str="", **kwargs) -> tuple[int, dict]:
        """Communicate to Rasa endpoint
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
                if not http_method: return 400, {"error": f"HTTP method {http_method} is not valid." }
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
        """Get all models in model dir"""
        return [Model.get_model(r.name) for r in MODEL_DIR.iterdir()]
