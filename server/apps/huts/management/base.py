from typing import Callable
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
import click
from django.db import models
from huts.managers import BaseManager
from django.core.management import call_command
import traceback
import shutil


def default_add_function(force: bool, model: models.Model, parser: BaseCommand, **kwargs_add):
    parser.stdout.write(f"Load data from '{model._meta.object_name}.yaml' fixtures")
    try:
        call_command("loaddata", model._meta.object_name, app_label=model._meta.app_label)
        parser.stdout.write(parser.style.SUCCESS(f"Successfully loaded data"))
    except Exception as e:
        parser.stderr.write(traceback.format_exc())
        parser.stdout.write(parser.style.ERROR(f"Loaddata failed, fix issues and run again"))
    if getattr(parser, "media_src"):
        media_dst = settings.MEDIA_ROOT if not getattr(parser, "media_dst") else getattr(parser, "media_dst")
        media_src = getattr(parser, "media_src")
        parser.stdout.write(f"Copy media files from '{media_src}' to '{media_dst}'")
        shutil.copytree(media_src, media_dst, dirs_exist_ok=True)


def default_drop_function(limit: int, offset: int, force: bool, model: models.Model, parser: BaseCommand, **kwargs_add):
    objects: BaseManager = model.__class__.objects  # type: ignore
    if click.confirm(f"Delete {limit or 'all'} entries (total: {objects.all().count()})?", default=True) or force:
        _d, tables = objects.drop(limit=limit, offset=offset)
        for table, deleted in tables.items():
            parser.stdout.write(f"  > dropped {deleted} entries from table '{table}'")


class CRUDCommand(BaseCommand):
    help = "Initialize and drop data in Organizations table"
    # suppressed_base_arguments = (
    #    "--version",
    #    "--settings",
    #    "--pythonpath",
    #    "--traceback",
    #    "--no-color",
    #    "--force-color",
    # )
    requires_system_checks = []
    model: models.Model | None = None
    add_function: None | Callable = (
        default_add_function  # add_function(parser, limit, offset, update, force, **kwargs_add)
    )
    media_src: str | None = None  # copy media file from this location to
    media_dst: str | None = None  # this location (destination is not required an per default settins.MEDIA_ROOT)
    drop_function: None | Callable = default_drop_function  # drop_function(parser, limit, offset, force, **kwargs_add)

    # def __init__(self, *args, **kwargs):
    #    super().__init__(*args, **kwargs)
    #    self._parser = None
    #    self._organization = None

    def add_arguments(self, parser):
        parser.add_argument("-d", "--drop", action="store_true", help="Drop entries in table")
        parser.add_argument("-a", "--add", action="store_true", help="Fill table with default entries")
        parser.add_argument("-u", "--update", action="store_true", help="Fill table with default entries")
        parser.add_argument("-n", "--limit", help="limit of entries", type=int)
        parser.add_argument("-o", "--offset", help="Offset from the source, per default limi of huts", type=int)
        parser.add_argument("-f", "--force", action="store_true", help="Fill table with default entries")

    def handle(
        self,
        drop: bool,
        add: bool,
        update: bool,
        force: bool,
        # init: bool,
        limit: int,
        offset: int | None,
        kwargs_add: dict | None = None,
        kwargs_drop: dict | None = None,
        *args,
        **options,
    ):
        if kwargs_add is None:
            kwargs_add = {}
        if self.model is None:
            raise AttributeError("'model' is needed!")
        objects: BaseManager = self.model.__class__.objects  # type: ignore
        if drop:
            if self.drop_function:
                self.drop_function(
                    parser=self, limit=limit, offset=offset, force=force, model=self.model, **kwargs_drop
                )
            else:
                raise NotImplemented("'drop_function' is not implemented")
        if add:
            entries = objects.all().count()
            if not limit:
                if force:
                    limit = entries
                limit = click.prompt("Limit of entries to add", type=int)

            if offset is None:
                offset = entries
            if self.add_function:
                self.add_function(
                    parser=self, limit=limit, offset=offset, update=update, force=force, model=self.model, **kwargs_add
                )
            else:
                raise NotImplemented("'add_function' is not implemented")
