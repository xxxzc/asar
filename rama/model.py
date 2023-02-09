"""Interact with Rasa Model"""
from rama import utils

from pathlib import Path
from dataclasses import dataclass

from rasa.cli.scaffold import create_initial_project
from rasa.model import get_latest_model
from typing import Optional
from functools import cache

from xmlrpc.client import ServerProxy
from supervisor.rpcinterface import SupervisorNamespaceRPCInterface


# http://supervisord.org/api.html#xml-rpc-api-documentation
supervisor: SupervisorNamespaceRPCInterface = ServerProxy( # type: ignore
    'http://localhost:9999/RPC2').supervisor



def full_path(path: Path):
    return path.absolute().as_posix()


class ModelStatus:
    NoDir = "nodir" # no model path
    Running = "running" # model is running
    Starting = "starting" # 


class Model:
    DIR = Path(__file__).parent.parent.parent / 'data' / 'model'
    """Represent model
    """

    def __init__(self, name) -> None:
        self.name = name

        self.dir: Path = Model.DIR / name

        # check dir
        if not self.dir.exists():
            create_initial_project(full_path(self.dir))
            
        self.models_dir = self.dir / 'models'

        

    def latest(self) -> Optional[Path]:
        model_path = get_latest_model(full_path(self.dir))
        if model_path is None:
            return None
        return Path(model_path)


    def check(self):
        """Check model"""
        # check models
        if not self.models_dir.exists():
            self.models_dir.mkdir(exist_ok=True)

        latest = self.latest()
        if latest is None: # no model
            # check if train task exists
            
            pass
        return