from server.core.management import CRUDCommand

from ...models import ContactFunction


class Command(CRUDCommand):
    # help = ""
    model = ContactFunction
    model_names = "contactfunctions"

    # def __init__(self, *args, **kwargs):
    #    super().__init__(*args, **kwargs)
    #    main_path = Path(self.app_label) / "types"
    #    self.set_media_paths(src=Path("assets") / main_path / "media", dst=main_path)
