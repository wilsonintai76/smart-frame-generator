import adsk.core
import adsk.fusion
from typing import List, Tuple
from member import FrameMember


def _log(message: str) -> None:
    """Writes a message to Fusion 360's Text Commands palette."""
    app = adsk.core.Application.get()
    palette = app.userInterface.palettes.itemById('TextCommands')
    if palette:
        palette.writeText(f"[SmartFrameGenerator] {message}")  # type: ignore[attr-defined]


class Trimmer:
    @staticmethod
    def execute(root_comp: adsk.fusion.Component,
                trim_queue: List[Tuple[FrameMember, FrameMember]]) -> None:
        """Iterates the trim queue and performs Combine → Cut for each T-joint pair.

        Bug #2 fix: errors are logged individually to the Text Commands palette
        instead of being silently swallowed. A summary is printed after all trims.
        """
        combines  = root_comp.features.combineFeatures
        succeeded = 0
        failed    = 0

        for tool, target in trim_queue:
            try:
                tool_collection = adsk.core.ObjectCollection.create()
                tool_collection.add(tool.body)

                combine_input = combines.createInput(target.body, tool_collection)
                combine_input.operation = adsk.fusion.FeatureOperations.CutFeatureOperation  # type: ignore[assignment]
                combine_input.isKeepToolBodies = True
                combines.add(combine_input)
                succeeded += 1

            except Exception as ex:
                failed += 1
                tool_name   = tool.component.name   if tool.component   else "unknown"
                target_name = target.component.name if target.component else "unknown"
                _log(f"  ✗ Trim failed — tool: '{tool_name}'  target: '{target_name}'  → {ex}")

        total = succeeded + failed
        _log(f"Trim complete: {succeeded}/{total} joints trimmed successfully."
             + (f"  ({failed} failed — see above)" if failed else ""))
