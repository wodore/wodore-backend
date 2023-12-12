from pathlib import Path

from huts.models import HutType

from server.core.management import CRUDCommand


class Command(CRUDCommand):
    # help = ""
    use_media_args = True
    model = HutType
    model_names = "huttypes"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        main_path = Path(self.app_label) / "types"
        self.set_media_paths(src=Path("assets") / main_path / "media", dst=main_path)
