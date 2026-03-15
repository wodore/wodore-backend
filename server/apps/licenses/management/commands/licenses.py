from server.core.management import CRUDCommand

from ...models import License


class Command(CRUDCommand):
    # help = ""
    use_media_args = True
    model = License
    model_names = "licenses"
    compare_fields = ("slug",)
    lookup_field = "slug"  # Use slug for identification, ignore fixture PKs

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    # def handle(self, *args, **options):
    #    super().handle(**options)
