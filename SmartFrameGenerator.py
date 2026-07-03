import os
import sys
import adsk.core
import traceback

# Force the main root directory into Python's system path mapping arrays
root_dir = os.path.dirname(os.path.abspath(__file__))
if root_dir not in sys.path:
    sys.path.append(root_dir)

from . import commands
from .lib import fusionAddInUtils as futil

def run(context: object) -> None:
    try:
        commands.start()
    except:
        ui = adsk.core.Application.get().userInterface
        ui.messageBox(f"SmartFrameGenerator Crashed on Startup!\n\n{traceback.format_exc()}")

def stop(context: object) -> None:
    try:
        futil.clear_handlers()
        commands.stop()
    except:
        futil.handle_error('stop')