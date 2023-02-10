from rama import utils
from pathlib import Path
from functools import cached_property
import asyncio
from dataclasses import dataclass
from typing import Optional

from sanic import Sanic
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


class Model:
    """Rasa Model

    use get_model to get model instance
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self.program = f"model_{name}"
        self.dir = MODEL_DIR / name
        self.setup_task = 0

    async def setup(self, force_train=False):
        if self.setup_task > 0:
            return utils.Result("setup_error", False, 
                f"There is already a <{self.name}> setup task, waiting...").log()

        self.setup_task = 1
        try:
            # check model dir
            await self.init()

            # train model if needed
            await self.train(force=force_train)

            # run latest model
            await self.run()
        except Exception as e:
            self.setup_task = 0
            return utils.Result("setup_error", False, str(e)).log()

        self.setup_task = 0
        return utils.Result("setup_success", True, 
            f"Setup <{self.name}> done. Current running model: {self.latest()}").log()


    async def init(self):
        if not self.dir.exists():
            logger.info(f"Model dir {self.dir} not exists, init it...")
            self.dir.mkdir(exist_ok=True, parents=True)
            init_process = await asyncio.create_subprocess_exec("rasa", "init",
                                                        "--no-prompt",
                                                        cwd=full_path(self.dir))
            await init_process.wait()
            logger.info(f"Model dir {self.dir} inited.")


    async def train(self, force=False):
        """Train model if needed"""
        models = self.get_path("models")
        models.mkdir(exist_ok=True, parents=True)
            
        need_train = False
        if not self.latest():
            logger.info("No trained model exists.")
            need_train = True
        if force:
            logger.info("Force to train.")
            need_train = True

        if need_train:  # train one
            logger.info("Traning, please wait...")
            train_process = await asyncio.create_subprocess_exec("rasa", "train",
                                                        "--num-threads", "8",
                                                        cwd=full_path(self.dir))
            await train_process.wait()


    async def run(self):
        """Run latest model"""
        conf = self.get_path("supervisor.conf")
        if not conf.exists():
            with open(conf, "w") as f:
                f.write("\n".join([
                    f"[program:{self.program}]",
                    f"command=rasa run -p {self.port} --cors * --enable-api --log-file run.log",
                    f"directory={full_path(self.dir)}"
                ]))

        try:
            info = svctl.getProcessInfo(self.program)
            if info['state'] != 20:
                logger.error("Model stopped, restarting it...")
                svctl.startProcess(self.program)
        except:
            logger.info("No running model exists, starting it...")
            # we should call update in command line
            # svctl.reloadConfig() # not working, it just print diff
            update_process = await asyncio.create_subprocess_exec("supervisorctl", "update",
                                                                cwd=ROOT)
            await update_process.wait()

        # wait for model to start
        timeout, minute, attempts = 300, 5, 1
        client = ClientSession()
        current_model: Optional[str] = None
        logger.info(f"Try to connect to <{self.name}>...")
        while attempts * minute < timeout:
            try:
                logger.info(f"Attempts {attempts}")
                async with client.get(self.get_url("status")) as resp:
                    if resp.status == 200:
                        result: dict = await resp.json()
                        current_model = result.get("model_file", "").split("/")[-1]
                        break
                    elif resp.status == 409: # run without model
                        break
            except:
                pass
            await asyncio.sleep(minute)
            attempts += 1
        
        latest_model = self.latest()
        if not latest_model:
            logger.error("No latest model found")
            return

        if not current_model or current_model != latest_model:
            # Call Rasa to replace model
            # this method will make model down a while
            # Start new rasa run to run new model and waiting this complete
            # https://rasa.com/docs/rasa/pages/http-api#operation/replaceModel
            try:
                logger.info("Current running model is not latest, replacing it...")
                async with client.put(self.get_url("model"), json={
                    "model_file": full_path(self.get_path("models") / latest_model)
                }) as resp:
                    if resp.status == 204:
                        logger.info("Model replaced!")
                    else:
                        result = await resp.json()
                        logger.error(f"Model replace failed: {result}")
            except Exception as e:
                logger.error(f"Model replace failed: {e}")
        await client.close()

    
    def latest(self) -> Optional[str]:
        """Latest trained model name"""
        latest = get_latest_model(full_path(self.get_path("models")))
        if not latest: return latest
        return latest.split('/')[-1]


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


    def get_path(self, sub: str="") -> Path:
        if not sub: return self.dir
        return self.dir / sub


    def get_url(self, path: str):
        return f"http://localhost:{self.port}/{path}"


    async def is_running(self, client: ClientSession):
        try:
            async with client.get(self.get_url("status")) as resp:
                if resp.status == 200:
                    return self.name
        except:
            pass
        return None
    


@lru_cache(None)
def get_model(name: str) -> Model:
    if name.startswith("model_"):
        name = name[6:]
    return Model(name)


def get_models() -> list[Model]:
    return [get_model(m.name) for m in MODEL_DIR.iterdir()]