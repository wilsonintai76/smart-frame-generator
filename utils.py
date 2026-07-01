import os
from typing import List

import adsk.core
import adsk.fusion

def get_resource_path(relative_path: str) -> str:
    """Generates an absolute platfrom-agnostic path targeting a subfolder resource."""
    addon_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(addon_dir, relative_path)

def get_active_design() -> adsk.fusion.Design | None:
    """Safely captures the top-level active modeling design workspace workspace."""
    app = adsk.core.Application.get()
    product = app.activeProduct
    return adsk.fusion.Design.cast(product)  # type: ignore[return-value]  # type: ignore[arg-type]

def get_available_custom_profiles() -> List[str]:
    """Queries the local root profile folder context directory seeking .f3d archives."""
    profiles_dir = get_resource_path('profiles')
    if not os.path.exists(profiles_dir):
        return []
    
    files = [f for f in os.listdir(profiles_dir) if f.lower().endswith('.f3d')]
    return [os.path.splitext(f)[0] for f in files]