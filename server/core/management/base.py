import os
import shutil
import sys
from pathlib import Path
from typing import Any, Generic, Protocol, Sequence, Tuple, TypeVar

import click
import yaml
from rich import print

from django.apps import apps
from django.conf import settings
from django.core import serializers
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandParser
from django.core.management.commands.loaddata import Command as LoadDataCommand
from django.db import (
    DEFAULT_DB_ALIAS,
    models,
)
from django.db.models.deletion import RestrictedError


def add_fixture_function(
    obj: "CRUDCommand", force: bool, model: models.Model, **kwargs: Any
) -> None:
    """
    Load data from fixture file into database.

    Supports two modes:
    1. Legacy mode: Uses compare_fields for update_or_create (can cause PK conflicts)
    2. Lookup field mode: Uses a single lookup_field (e.g., 'slug') for identification,
       ignoring fixture PKs entirely (safer, works with slugs/natural keys)

    Media files are properly uploaded using Django's storage system (S3 compatible).
    """
    from django.core.files import File as DjangoFile

    ignore_media = kwargs.get("ignore_media", False)
    compare_fields = getattr(
        obj,
        "compare_fields",
        [
            "id",
        ],
    )
    # New parameter: use a single field for lookup instead of compare_fields
    lookup_field = getattr(obj, "lookup_field", None)
    fixture_name = getattr(obj, "fixture_name", "")
    obj.stdout.write(f"Load data from '{fixture_name}.yaml' fixtures")

    if not force and model.objects.all().count() > 0:
        try:
            force = click.confirm(
                "Careful this might overwrite existing data in the database, continue?",
                default=True,
            )
        except click.Abort:
            print()
            sys.exit(0)

    if force or model.objects.all().count() == 0:
        try:
            loaddata_command = LoadDataCommand()
            loaddata_command.verbosity = 0
            loaddata_command.app_label = obj.app_label
            loaddata_command.using = DEFAULT_DB_ALIAS
            loaddata_command.ignore = True
            loaddata_command.exclude = []
            loaddata_command.format = None
            loaddata_command.serialization_formats = (
                serializers.get_public_serializer_formats()
            )

            fixture_files = loaddata_command.find_fixtures(fixture_name)
            if not fixture_files:
                obj.stdout.write(
                    obj.style.ERROR(
                        f"Could not find fixture '{fixture_name}' for model '{obj.model}'."
                    )
                )
                return
            fixture_file = fixture_files[0][0]  # Get the first fixture file
            obj.stdout.write(obj.style.NOTICE(f"Fixture file: {fixture_file}"))

            with open(fixture_file) as f:
                fixture_data = yaml.safe_load(f)

            for item in fixture_data:
                if "model" not in item or "fields" not in item:
                    obj.stdout.write(
                        obj.style.WARNING(f"Skipping invalid fixture item: {item}")
                    )
                    continue

                item_fields = item["fields"]

                try:
                    fixture_model = apps.get_model(*item["model"].split("."))
                except LookupError:
                    obj.stdout.write(
                        obj.style.ERROR(
                            f"Could not find model '{item['model']}' from fixture '{fixture_file}'."
                        )
                    )
                    continue

                # Handle media files with proper storage upload (S3 compatible)
                if not ignore_media:
                    for field in fixture_model._meta.get_fields():
                        if field.name in item_fields and isinstance(
                            field, (models.FileField, models.ImageField)
                        ):
                            img_path = item_fields[field.name]
                            if not img_path or img_path == "":
                                continue

                            file_path = os.path.realpath(
                                os.path.join(
                                    obj.media_src if obj.media_src is not None else "",
                                    img_path,
                                )
                            )

                            if os.path.exists(file_path):
                                # Store the file path for later use during model save
                                # We'll open it when the model saves to avoid "seek of closed file"
                                item_fields[f"{field.name}_path"] = file_path
                                item_fields[f"{field.name}_name"] = os.path.basename(
                                    img_path
                                )
                                # Remove the original field value so Django doesn't try to use it
                                del item_fields[field.name]
                            else:
                                obj.stdout.write(
                                    obj.style.ERROR(
                                        f"Could not find file '{file_path}' from fixture '{fixture_file}'."
                                    )
                                )

                # Handle record identification and PK assignment
                if lookup_field:
                    # New mode: Use single lookup field (e.g., 'slug') to find existing entry
                    lookup_value = item_fields.get(lookup_field)
                    if not lookup_value:
                        obj.stdout.write(
                            obj.style.ERROR(
                                f"Item missing lookup field '{lookup_field}', skipping: {item}"
                            )
                        )
                        continue

                    try:
                        # Check if record exists by lookup field
                        lookup_kwargs = {lookup_field: lookup_value}
                        existing_obj = model.objects.get(**lookup_kwargs)
                        # Use existing object's ID
                        item_fields["id"] = existing_obj.id
                    except model.DoesNotExist:
                        # New record: get next available ID
                        last_id = (
                            model.objects.all()
                            .order_by("-id")
                            .values_list("id", flat=True)
                            .first()
                        )
                        if last_id is not None:
                            item_fields["id"] = last_id + 1
                        else:
                            item_fields["id"] = 1  # First record

                # Build comparison dict for update_or_create
                if lookup_field:
                    # Use lookup field for comparison
                    compare_dict = {lookup_field: item_fields[lookup_field]}
                else:
                    # Legacy mode: Use compare_fields
                    compare_dict = {
                        k: v
                        for k, v in item_fields.items()
                        if k in compare_fields and k not in ["id", "pk"]
                    }
                    if "id" in compare_fields or "pk" in compare_fields:
                        compare_dict["id"] = item.get("pk", item_fields.get("id"))

                # Handle file uploads before saving model
                # We need to process files that were stored as paths
                file_fields_to_process = {}
                if not ignore_media:
                    for field in fixture_model._meta.get_fields():
                        if isinstance(field, (models.FileField, models.ImageField)):
                            path_key = f"{field.name}_path"
                            name_key = f"{field.name}_name"

                            if path_key in item_fields and name_key in item_fields:
                                file_fields_to_process[field.name] = {
                                    "path": item_fields[path_key],
                                    "name": item_fields[name_key],
                                }
                                # Remove the temp keys
                                del item_fields[path_key]
                                del item_fields[name_key]

                # Use update_or_create for both modes
                m, created = model.objects.update_or_create(
                    **compare_dict, defaults=item_fields
                )

                # Now handle the file uploads if there are any
                if file_fields_to_process:
                    for field_name, file_info in file_fields_to_process.items():
                        try:
                            field = fixture_model._meta.get_field(field_name)
                            # Delete old file if updating
                            if (
                                not created
                                and hasattr(m, field_name)
                                and getattr(m, field_name)
                            ):
                                getattr(m, field_name).delete(save=False)

                            # Upload new file using Django's storage backend
                            with open(file_info["path"], "rb") as f:
                                django_file = DjangoFile(f, name=file_info["name"])
                                getattr(m, field_name).save(
                                    file_info["name"], django_file, save=True
                                )

                            obj.stdout.write(
                                obj.style.SUCCESS(
                                    f"  Uploaded file '{file_info['name']}' to field '{field_name}'"
                                )
                            )
                        except Exception as e:
                            obj.stdout.write(
                                obj.style.ERROR(
                                    f"Failed to upload file '{file_info['path']}': {e}"
                                )
                            )

                if created:
                    obj.stdout.write(
                        f"Created new entry '{m}' in {fixture_model._meta.db_table}"
                    )
                else:
                    obj.stdout.write(
                        f"Updated entry '{m}' in {fixture_model._meta.db_table}"
                    )

            obj.stdout.write("Fixture loaded successfully")

        except Exception as e:
            obj.stdout.write(f"Error loading fixture: {e}")
            import traceback

            obj.stdout.write(traceback.format_exc())
            sys.exit(1)


def dump_fixture_function(
    obj: "CRUDCommand", force: bool, model: models.Model, **kwargs: Any
) -> None:
    fixture_name = getattr(obj, "fixture_name", "")
    fixture_path = obj.get_app_path() / "fixtures" / f"{fixture_name}.yaml"
    fixture_path_rel = fixture_path.relative_to(settings.BASE_DIR)
    meta = model._meta
    try:
        if os.path.exists(fixture_path) and not force:
            do_abort = False
            try:
                if not click.confirm(
                    f"File '{fixture_path_rel}', overwrite?", default=True
                ):
                    do_abort = True
            except click.Abort:
                print()
                do_abort = True
            if do_abort:
                obj.stdout.write(
                    obj.style.NOTICE(f"Do not write file '{fixture_path_rel}'")
                )
                sys.exit(0)

        call_command(
            "dumpdata",
            f"{obj.app_label}.{meta.object_name}",
            format="yaml",
            output=fixture_path,
        )
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
                    f"Make sure to manually copy any new/changed media files from '{obj.media_dst.relative_to(settings.BASE_DIR)}' to '{obj.media_src.relative_to(settings.BASE_DIR)}'"
                )
            )
        obj.stdout.write(
            obj.style.SUCCESS(f"Successfully saved data to '{fixture_path_rel}'")
        )
    except Exception as e:
        obj.stdout.write(
            obj.style.ERROR("Save data failed, fix issue and run again, error message:")
        )
        obj.stdout.write(obj.style.NOTICE(e.args[0]))
        sys.exit(1)


def default_drop_function(
    obj: "CRUDCommand", force: bool, model: models.Model, **kwargs: None
) -> None:
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
            db_force = click.confirm(
                f"Delete {limit or 'all'} entries (total: {objects.all().count()})?",
                default=True,
            )
        except click.Abort:
            db_force = False
            print()
    if entries == 0:
        obj.stdout.write(
            obj.style.NOTICE(
                f"Nothing to delete in table '{obj.app_label}.{model._meta.object_name}'"
            )
        )
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
            obj.stdout.write(
                obj.style.ERROR(
                    "Cannot drop due to restictions. Solve it first! The restriction is:"
                )
            )
            obj.stdout.write(obj.style.NOTICE(e.args[0]))
            sys.exit(1)
    # media_src, media_dst = get_media(parser)
    if obj.media_src and not ignore_media and obj.media_dst.exists:
        media_dst_rel = obj.media_dst.relative_to(settings.BASE_DIR)
        if os.path.exists(obj.media_dst):
            media_force = force
            if not media_force:
                try:
                    media_force = click.confirm(
                        f"Remove media file folder '{media_dst_rel}'?", default=True
                    )
                except click.Abort:
                    media_force = False
                    print()
            if media_force:
                shutil.rmtree(obj.media_dst)
                obj.stdout.write(
                    obj.style.SUCCESS(f"Successfully removed '{media_dst_rel}'")
                )
        else:
            obj.stdout.write(
                obj.style.NOTICE(f"Path '{media_dst_rel}' already removed")
            )


TModel = TypeVar("TModel", bound=models.Model)

TFModel = TypeVar("TFModel", bound=models.Model)


class CRUDFunction(Protocol, Generic[TFModel]):
    __name__: str

    def __call__(
        self,
        obj: "CRUDCommand[TFModel]",
        force: bool,
        model: models.Model,
        **kwargs: Any,
    ) -> None:
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
    media_dst: str | Path | None = (
        None  # this location (destination is not required an per default settins.MEDIA_ROOT)
    )
    fixture_name: str = (
        ""  # name for fixture under <app_label>/fixtures/<fixture_name>.yaml
    )
    compare_fields: Sequence[str] = [
        "id"
    ]  # compare on this fields, if it exists it is only update
    lookup_field: str | None = (
        None  # use single field for lookup (e.g., 'slug'), ignores fixture PKs
    )

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
        self.model_names = (
            self.model_names or self.model._meta.object_name.lower() + "s"
        )
        self.app_label = self.app_label or self.model._meta.app_label
        self.fixture_name = self.fixture_name or self.model_names
        if not self.fixture_name:
            err_msg = "'fixture_name' is needed, add it to the global variables in your class!"
            raise AttributeError(err_msg)
        if (
            self.media_src
            and (self.use_media_args is not False or self.use_media_args is None)
        ) or self.use_media_args:
            self.set_media_paths()

    def add_arguments(self, parser: CommandParser) -> None:
        if self.drop_function:
            parser.add_argument(
                "-d", "--drop", action="store_true", help="Drop entries in table"
            )
        if self.add_function:
            parser.add_argument(
                "-a", "--add", action="store_true", help="Add data to table"
            )
        if self.use_update_arg:
            parser.add_argument(
                "-u", "--update", action="store_true", help="Update existing entries"
            )
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
            "-f",
            "--force",
            action="store_true",
            help="Force, e.g. overwrite existing data (be careful!)",
        )
        if (
            self.add_function is not None
            and self.add_function.__name__ == "add_fixture_function"
        ):
            parser.add_argument(
                "--fixture-name",
                help=f"Name of the fixtues (default: {self.fixture_name})",
            )
        if self.media_src:
            parser.add_argument(
                "--ignore-media",
                action="store_true",
                help="Ignore media files (do not copy or remove)",
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
        dump = options.get("dump")
        drop = options.get("drop")
        add = options.get("add")
        update = options.get("update")
        ## set optional kwargs
        kwargs = {}
        ##   fixture name
        if options.get("fixture_name"):
            self.fixture_name = options.get("fixture_name", False)
            kwargs["fixture_name"] = options.get("fixture_name", False)
        if options.get("media_src"):
            self.fixture_name = options.get("media_src", "")
            kwargs["media_src"] = options.get("media_src", "")
        ##   limit
        if self.use_limit_arg:
            limit = options.get("limit")
            if not limit:
                default_value = self.default_limit(drop=drop, add=add, update=update)
                if force:
                    limit = default_value
                else:
                    try:
                        limit = click.prompt(
                            "Limit of entries to add (--limit)",
                            type=int,
                            default=default_value,
                        )
                    except click.Abort:
                        print()
                        sys.exit(0)
            kwargs["limit"] = limit
        ##   offset
        if self.use_offset_arg:
            offset = options.get("offset")
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
                self.stdout.write(
                    self.style.WARNING("'drop_function' is not implemented")
                )
        ## ADD
        if add:
            if self.add_function:
                self.add_function(
                    update=update, force=force, model=self.model, **kwargs_add
                )
            else:
                self.stdout.write(
                    self.style.WARNING("'add_function' is not implemented")
                )
        ## ADD
        if dump:
            if self.dump_function:
                self.dump_function(force=force, model=self.model, **kwargs_add)
            else:
                self.stdout.write(
                    self.style.WARNING("'dump_function' is not implemented")
                )

    def get_app_path(self) -> Path:
        return Path(settings.BASE_DIR) / "server" / "apps" / self.app_label

    def get_media_paths(self) -> Tuple[Path | None, Path | None]:
        if (self.media_src and self.use_media_args is not False) or self.use_media_args:
            media_dst = Path(str(self.media_dst))
            media_src = Path(str(self.media_src))
            if not media_src.exists():
                self.stdout.write(
                    self.style.ERROR(
                        f"'media_src' directory '{media_src}' does not exist."
                    )
                )
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
