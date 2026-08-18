from pathlib import Path

from fastapi.templating import Jinja2Templates

from app.web.profile_style import profile_color
from app.web.timeutil import to_local, to_local_short

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.filters["local_time"] = to_local
templates.env.filters["local_time_short"] = to_local_short
templates.env.filters["profile_color"] = profile_color
