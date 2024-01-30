import os
import shutil
import sys
from pathlib import Path
from typing import Any, Callable, ClassVar, Generic, Protocol, Tuple, TypeVar

import click

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandParser
from django.db import models
from django.db.models.deletion import RestrictedError

from server.core.managers import BaseManager


def add_fixture_function(obj: "CRUDCommand", force: bool, model: models.Model, **kwargs: Any) -> None:
    ignore_media = kwargs.get("ignore_media", False)
    fixture_name = getattr(obj, "fixture_name", "")
    obj.stdout.write(f"Load data from '{fixture_name}.yaml' fixtures")
    if not force and model.objects.all().count() > 0:
        try:
            force = click.confirm("Careful this might overwrite exisitng data in the database, continue?", default=True)
        except click.Abort:
            print()
            sys.exit(0)
    if force or model.objects.all().count() == 0:
        try:
            call_command("loaddata", fixture_name, app_label=obj.app_label)
            obj.stdout.write(obj.style.SUCCESS("Successfully loaded data"))
        except Exception as e:
            obj.stdout.write(obj.style.ERROR("Loaddata failed, fix issues and run again, error message:"))
            obj.stdout.write(obj.style.NOTICE(e.args[0]))
            sys.exit(1)
        if obj.media_src and not ignore_media:
            media_src_rel = obj.media_src.relative_to(settings.BASE_DIR)
            media_dst_rel = obj.media_dst.relative_to(settings.BASE_DIR)
            obj.stdout.write(f"Copy media files from '{media_src_rel}' to '{media_dst_rel}'")
            try:
                shutil.copytree(obj.media_src, obj.media_dst, dirs_exist_ok=True)
                obj.stdout.write(obj.style.SUCCESS("Successfully copied data"))
            except FileNotFoundError as e:
                obj.stdout.write(obj.style.ERROR("Could not copy files, error message:"))
                obj.stdout.write(obj.style.NOTICE(e.args[1]))
                sys.exit(1)


def dump_fixture_function(obj: "CRUDCommand", force: bool, model: models.Model, **kwargs: Any) -> None:
    fixture_name = getattr(obj, "fixture_name", "")
    fixture_path = obj.get_app_path() / "fixtures" / f"{fixture_name}.yaml"
    fixture_path_rel = fixture_path.relative_to(settings.BASE_DIR)
    meta = model._meta
    try:
        if os.path.exists(fixture_path) and not force:
            do_abort = False
            try:
                if not click.confirm(f"File '{fixture_path_rel}', overwrite?", default=True):
                    do_abort = True
            except click.Abort:
                print()
                do_abort = True
            if do_abort:
                obj.stdout.write(obj.style.NOTICE(f"Do not write file '{fixture_path_rel}'"))
                sys.exit(0)

        call_command("dumpdata", f"{obj.app_label}.{meta.object_name}", format="yaml", output=fixture_path)
        with open(fixture_path) as file:
            new_lines = []  # remove created and modified
            for line in file.readlines():
                if "    modified: " not in line and "    created: " not in line:
                    new_lines.append(line)
        with open(fixture_path, "w") as file:
            file.writelines(new_lines)
        if obj.media_src:
            obj.stdout.write(
                obj.style.WARNING(
                    f"Make sure to manually copy any new/changed logo from '{obj.media_dst.relative_to(settings.BASE_DIR)}' to '{obj.media_src.relative_to(settings.BASE_DIR)}'"
                )
            )
        obj.stdout.write(obj.style.SUCCESS(f"Successfully saved data to '{fixture_path_rel}'"))
    except Exception as e:
        obj.stdout.write(obj.style.ERROR("Save data failed, fix issue and run again, error message:"))
        obj.stdout.write(obj.style.NOTICE(e.args[0]))
        sys.exit(1)


def default_drop_function(obj: "CRUDCommand", force: bool, model: models.Model, **kwargs: None) -> None:
    limit = kwargs.get("limit")
    offset = kwargs.get("offset")
    ignore_media = kwargs.get("ignore_media", False)
    # objects: BaseManager = model.objects
    objects = model.objects
    entries = model.objects.all().count()
    db_force = force
    # check support for limit
    err_msg = "'{}' parameter is not supported without custom manager's 'drop()' function (see 'server.core.managers')"
    if not hasattr(objects, "drop") and obj.use_limit_arg:
        obj.stdout.write(obj.style.WARNING(err_msg.format("--limit")))
        limit = None
    if not hasattr(objects, "drop") and obj.use_offset_arg:
        obj.stdout.write(obj.style.WARNING(err_msg.format("--offset")))
        offset = 0

    if not db_force and entries > 0:
        try:
            db_force = click.confirm(f"Delete {limit or 'all'} entries (total: {objects.all().count()})?", default=True)
        except click.Abort:
            db_force = False
            print()
    if entries == 0:
        obj.stdout.write(obj.style.NOTICE(f"Nothing to delete in table '{obj.app_label}.{model._meta.object_name}'"))
        db_force = False
    if db_force:
        try:
            if hasattr(objects, "drop"):
                total_entries, tables = objects.drop(limit=limit, offset=offset)
            else:
                total_entries, tables = objects.all().delete()
            for table, deleted in tables.items():
                obj.stdout.write(f"  > dropped {deleted} entries from table '{table}'")
            obj.stdout.write(
                obj.style.SUCCESS(
                    f"Successfully dropped {total_entries} entries from {len(tables)} table{'s' if len(tables) else ''}"
                )
            )
        except RestrictedError as e:
            obj.stdout.write(obj.style.ERROR("Cannot drop due to restictions. Solve it first! The restriction is:"))
            obj.stdout.write(obj.style.NOTICE(e.args[0]))
            sys.exit(1)
    # media_src, media_dst = get_media(parser)
    if obj.media_src and not ignore_media and obj.media_dst.exists:
        media_dst_rel = obj.media_dst.relative_to(settings.BASE_DIR)
        if os.path.exists(obj.media_dst):
            media_force = force
            if not media_force:
                try:
                    media_force = click.confirm(f"Remove media file folder '{media_dst_rel}'?", default=True)
                except click.Abort:
                    media_force = False
                    print()
            if media_force:
                shutil.rmtree(obj.media_dst)
                obj.stdout.write(obj.style.SUCCESS(f"Successfully removed '{media_dst_rel}'"))
        else:
            obj.stdout.write(obj.style.NOTICE(f"Path '{media_dst_rel}' already removed"))


TModel = TypeVar("TModel", bound=models.Model)

TFModel = TypeVar("TFModel", bound=models.Model)


class CRUDFunction(Protocol, Generic[TFModel]):
    __name__: str

    def __call__(self, obj: "CRUDCommand[TFModel]", force: bool, model: models.Model, **kwargs: Any) -> None:
        pass


class CRUDCommand(BaseCommand, Generic[TModel]):
    help = "Drop, add, update and save entries from, respectively, to database table."

    model: TModel  # REQUIRED
    model_names: str  # REQUIRED
    app_label: str = ""  # if not main app model

    # general settings
    use_offset_arg: bool = False
    use_limit_arg: bool = False
    use_update_arg: bool = False
    use_media_args: bool | None = (
        None  # if None use it if media_src is set, if False never us it if True auto generate media_src if no given
    )

    # add settings
    add_function: None | CRUDFunction[TModel] = add_fixture_function
    media_src: str | Path | None = None  # copy media file from this location to
    media_dst: str | Path | None = None  # this location (destination is not required an per default settins.MEDIA_ROOT)
    fixture_name: str = ""  # name for fixture under <app_label>/fixtures/<fixture_name>.yaml

    # drop settings
    drop_function: None | CRUDFunction[TModel] = (
        default_drop_function  # drop_function(parser, limit, offset, force, **kwargs_add)
    )

    # dump settings
    dump_function: None | CRUDFunction[TModel] = dump_fixture_function

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # BaseCommand settings
        self.suppressed_base_arguments = {
            "--version",
            "--settings",
            "--pythonpath",
            "--traceback",
            "--no-color",
            "--force-color",
        }
        self.requires_system_checks = []  # type: ignore pyright

        ##   check for model
        if self.model is None:
            err_msg = "'model' is needed, add it to the global variables in your class!"
            raise AttributeError(err_msg)
        # set default attributes
        self.model_names = self.model_names or self.model._meta.object_name.lower() + "s"
        self.app_label = self.app_label or self.model._meta.app_label
        self.fixture_name = self.fixture_name or self.model_names
        if not self.fixture_name:
            err_msg = "'fixture_name' is needed, add it to the global variables in your class!"
            raise AttributeError(err_msg)
        if (
            self.media_src and (self.use_media_args is not False or self.use_media_args is None)
        ) or self.use_media_args:
            self.set_media_paths()

    def add_arguments(self, parser: CommandParser) -> None:
        if self.drop_function:
            parser.add_argument("-d", "--drop", action="store_true", help="Drop entries in table")
        if self.add_function:
            parser.add_argument("-a", "--add", action="store_true", help="Add data to table")
        if self.use_update_arg:
            parser.add_argument("-u", "--update", action="store_true", help="Update existing entries")
        if self.use_limit_arg:
            parser.add_argument("-l", "--limit", help="Limit of entries", type=int)
        if self.use_offset_arg:
            parser.add_argument("-o", "--offset", help="Offset of entries", type=int)
        if self.dump_function:
            parser.add_argument(
                "--dump",
                action="store_true",
                help="Dump entries from database as fixture (overwrites  '<app_label>/fixtures/<fixture-name>.yaml'). "
                "The file can be loaded with '--add' again into the database. "
                "Use '--fixture-name' in order to change the default name.",
            )
        parser.add_argument(
            "-f", "--force", action="store_true", help="Force, e.g. overwrite existing data (be careful!)"
        )
        if self.add_function is not None and self.add_function.__name__ == "add_fixture_function":
            parser.add_argument("--fixture-name", help=f"Name of the fixtues (default: {self.fixture_name})")
        if self.media_src:
            parser.add_argument(
                "--ignore-media", action="store_true", help="Ignore media files (do not copy or remove)"
            )
            parser.add_argument(
                "-m",
                "--media-src",
                help=f"Media source path (default: {self.media_src.relative_to(settings.BASE_DIR)})",
            )

    def default_limit(self, drop: bool, add: bool, update: bool, **kwargs: Any) -> int:
        if drop:  # drop and add the same amount
            return int(self.model.objects.all().count())
        # elif add:
        return 100000  # all

    def handle(
        self,
        force: bool,
        # init: bool,
        kwargs_add: dict | None = None,
        kwargs_drop: dict | None = None,
        kwargs_dump: dict | None = None,
        *args: Any,
        **options: Any,
    ) -> None:
        ##   defaults
        dump = options.get("dump", None)
        drop = options.get("drop", None)
        add = options.get("add", None)
        update = options.get("update", None)
        ## set optional kwargs
        kwargs = {}
        ##   fixture name
        if options.get("fixture_name", None):
            self.fixture_name = options.get("fixture_name", False)
            kwargs["fixture_name"] = options.get("fixture_name", False)
        if options.get("media_src", None):
            self.fixture_name = options.get("media_src", "")
            kwargs["media_src"] = options.get("media_src", "")
        ##   limit
        if self.use_limit_arg:
            limit = options.get("limit", None)
            if not limit:
                default_value = self.default_limit(drop=drop, add=add, update=update)
                if force:
                    limit = default_value
                else:
                    try:
                        limit = click.prompt("Limit of entries to add (--limit)", type=int, default=default_value)
                    except click.Abort:
                        print()
                        sys.exit(0)
            kwargs["limit"] = limit
        ##   offset
        if self.use_offset_arg:
            offset = options.get("offset", None)
            if offset is None:
                offset = 0
            kwargs["offset"] = offset
        ##   meda stuff
        if self.media_src:
            kwargs["ignore_media"] = options.get("ignore_media", False)
            kwargs["media_src"] = options.get("media_src", False)
        ##   default add
        if kwargs_add is None:
            kwargs_add = {}
        kwargs_add.update(kwargs)
        ##   default drop
        if kwargs_drop is None:
            kwargs_drop = {}
        kwargs_drop.update(kwargs)
        ## DROP
        if drop:
            if self.drop_function:
                self.drop_function(force=force, model=self.model, **kwargs_drop)
            else:
                self.stdout.write(self.style.WARNING("'drop_function' is not implemented"))
        ## ADD
        if add:
            if self.add_function:
                self.add_function(update=update, force=force, model=self.model, **kwargs_add)
            else:
                self.stdout.write(self.style.WARNING("'add_function' is not implemented"))
        ## ADD
        if dump:
            if self.dump_function:
                self.dump_function(force=force, model=self.model, **kwargs_add)
            else:
                self.stdout.write(self.style.WARNING("'dump_function' is not implemented"))

    def get_app_path(self) -> Path:
        return Path(settings.BASE_DIR) / "server" / "apps" / self.app_label

    def get_media_paths(self) -> Tuple[Path | None, Path | None]:
        if (self.media_src and self.use_media_args is not False) or self.use_media_args:
            media_dst = Path(str(self.media_dst))
            media_src = Path(str(self.media_src))
            if not media_src.exists():
                self.stdout.write(self.style.ERROR(f"'media_src' directory '{media_src}' does not exist."))
                sys.exit(1)
            return media_src, media_dst
        return None, None

    def set_media_paths(
        self, src: Path | str | None = None, dst: Path | str | None = None
    ) -> Tuple[Path | None, Path | None]:
        """Set media source and destination path, starint add app root, respecively, media root"""
        if src is None:
            default_src = Path("media") / self.app_label / self.model_names
            self.media_src = self.media_src or self.get_app_path() / default_src
        else:
            self.media_src = self.get_app_path() / src
        if dst is None:
            default_dst = Path(self.app_label) / self.model_names
            self.media_dst = self.media_dst or settings.MEDIA_ROOT / default_dst
        else:
            self.media_dst = settings.MEDIA_ROOT / dst
        # make sure it is a Path object
        if self.media_src:
            self.media_src = Path(self.media_src)
        if self.media_dst:
            self.media_dst = Path(self.media_dst)
        if self.media_src is not None:
            self.media_src = Path(self.media_src)
        if self.media_dst is not None:
            self.media_dst = Path(self.media_dst)
        return self.media_src, self.media_dst
