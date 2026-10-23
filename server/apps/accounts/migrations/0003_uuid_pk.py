"""Convert user keys from integer to UUID v4.

Runs while there is no production user base (spec: account-management D7):
the only accounts on dev/test databases are fixture users (re-create them
with ``local_auth_users`` afterwards); production and staging have none
yet. Changing a user PK type after real accounts exist would require a
row-preserving rewrite of every FK — now it is a wipe-and-convert.

What it does, on any database shape:

- Finds every concrete field with a FK to the user model through the
  *migration state* (natural-key match — swappable FKs on historical
  models resolve against the real registry, so identity checks find
  nothing). ``ON DELETE`` actions therefore come from the models, not
  from possibly-degraded database constraints — see 0002, which re-added
  retargeted constraints without their ``ON DELETE`` clause.
- Detaches user rows: ``DELETE`` from referencing tables with NOT NULL
  columns (allauth, oauth2_provider, admin log, M2M through tables, …),
  ``SET NULL`` for nullable ones (django-admin-runner ``triggered_by``,
  images/symbols upload grants keep their rows).
- Legacy pre-switch shadow tables (``auth_user_groups`` &
  ``auth_user_user_permissions``, retargeted to accounts_user by 0002)
  have no state model: their rows are wiped and their constraints
  dropped for good — the columns stay integer, inert and unconstrained.
- Deletes all users, flushes the deferred-constraint queue
  (``SET CONSTRAINTS ALL IMMEDIATE`` — 0002 left the retargeted FKs
  DEFERRABLE INITIALLY DEFERRED, whose pending checks would otherwise
  block the ALTERs), rewrites ``accounts_user.id`` and every state-target
  column to ``uuid``, then re-adds each FK constraint under its original
  name with the model-correct ``ON DELETE`` action and its introspected
  ``DEFERRABLE`` state.

On fresh databases the deletes hit zero rows and this is a pure type
change. Effectively irreversible (uuid -> int is lossy); reverse is a no-op.

Identifiers interpolated into the statements come from the Django model
state and pg_catalog introspection only and are composed with
``psycopg.sql.Identifier`` (identifiers cannot be bound as parameters).
"""

import os
import uuid

from psycopg import sql

from django.db import migrations, models

ON_DELETE_SQL = {
    models.CASCADE: "CASCADE",
    models.PROTECT: "RESTRICT",
    models.SET_NULL: "SET NULL",
    models.SET_DEFAULT: "SET DEFAULT",
    models.DO_NOTHING: "NO ACTION",
}

USER_MODEL_KEY = ("accounts", "user")


def _user_fk_fields(apps):
    """(db_table, column, on_delete_sql, nullable) for every FK to User."""
    targets = []
    # include_auto_created: the M2M through tables (user_groups,
    # user_user_permissions) are auto-created models - without them they
    # would be mistaken for legacy shadows and left integer.
    for model in apps.get_models(include_auto_created=True):
        for field in model._meta.get_fields():
            rel = field.related_model if field.is_relation else None
            if (
                (field.many_to_one or field.one_to_one)
                and field.concrete
                and field.column
                and rel is not None
                and (rel._meta.app_label, rel._meta.model_name) == USER_MODEL_KEY
            ):
                targets.append(
                    (
                        model._meta.db_table,
                        field.column,
                        ON_DELETE_SQL.get(field.remote_field.on_delete, "NO ACTION"),
                        field.null,
                    )
                )
    return targets


def to_uuid_pk(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return  # dev/test lanes and production are postgres; nothing else

    # Safety net: this migration wipes every user row (by design - spec D7
    # says production has no user base yet, and deploys run migrations
    # automatically). If an account somehow exists on a production
    # database (bootstrap before first deploy, delayed rollout), refuse
    # loudly instead of silently locking everyone out.
    if os.environ.get("DJANGO_ENV") == "production":
        with schema_editor.connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM accounts_user LIMIT 1")
            if cursor.fetchone():
                raise RuntimeError(
                    "uuid_pk: production database already has users - refusing "
                    "to wipe them (spec D7 assumes none). Delete them "
                    "deliberately or bootstrap after this migration."
                )

    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT cl.relname AS table_name,
                   a.attname  AS column_name,
                   c.conname  AS constraint_name,
                   c.condeferrable
            FROM pg_constraint c
            JOIN pg_class cl ON cl.oid = c.conrelid
            JOIN pg_attribute a ON a.attrelid = cl.oid AND a.attnum = c.conkey[1]
            WHERE c.contype = 'f'
              AND c.confrelid = 'accounts_user'::regclass
              AND cardinality(c.conkey) = 1
            """
        )
        # (table, column) -> [constraint_name, ...] - a column can carry
        # more than one FK to the user table (0002's retargeted legacy
        # constraint plus a later migration's fresh one); drop them all,
        # re-add exactly one. Prefer the name of the freshest constraint
        # (the post-switch fk_accounts_user_id suffix) for the re-add.
        constraint_names: dict[tuple[str, str], list[str]] = {}
        deferrable_flags: dict[tuple[str, str], bool] = {}
        for table, column, name, deferrable in cursor.fetchall():
            constraint_names.setdefault((table, column), []).append(name)
            # pg_catalog row order is unspecified; tie the deferrable flag
            # to the same constraint pick_name prefers (the post-switch
            # fk_accounts_user_id one) so name and flag always describe
            # the same constraint on re-add.
            if name.endswith("fk_accounts_user_id") or (
                (table, column) not in deferrable_flags
            ):
                deferrable_flags[(table, column)] = deferrable

        def pick_name(key: tuple[str, str]) -> str:
            names = sorted(
                constraint_names[key],
                key=lambda n: not n.endswith("fk_accounts_user_id"),
            )
            return names[0]

        # Historical model state can yield the same FK more than once
        # (e.g. symbols.uploaded_by_user) - dedupe by (table, column) so
        # each constraint is dropped/converted/re-added exactly once.
        targets = list(
            {(t, c): (t, c, od, nl) for t, c, od, nl in _user_fk_fields(apps)}.values()
        )
        missing = [(t, c) for t, c, _, _ in targets if (t, c) not in constraint_names]
        if missing:
            raise RuntimeError(
                f"uuid_pk: no FK constraint found for {missing} - "
                "refusing to convert; inspect the database manually"
            )
        # Pre-switch auth_user through tables retargeted by 0002: no state
        # model, dead data - wipe them so the parent delete passes.
        shadows = [
            (t, c)
            for t, c in constraint_names
            if (t, c) not in {(t, c) for t, c, _, _ in targets}
        ]

        # Detach: wipe dependent rows (fixture auth data), keep nullable
        # references as NULL. Explicit per-table so degraded ON DELETE
        # actions on pre-switch databases cannot block the user delete.
        for table, column, _, nullable in targets:
            if nullable:
                cursor.execute(
                    sql.SQL(
                        """UPDATE {0} SET {1} = NULL WHERE {2} IS NOT NULL"""
                    ).format(
                        sql.Identifier(table),
                        sql.Identifier(column),
                        sql.Identifier(column),
                    )
                )
            else:
                cursor.execute(
                    sql.SQL("""DELETE FROM {0}""").format(sql.Identifier(table))
                )
        for table, column in shadows:
            cursor.execute(sql.SQL("""DELETE FROM {0}""").format(sql.Identifier(table)))
        cursor.execute("DELETE FROM accounts_user")

        # 0002 left the retargeted FKs DEFERRABLE INITIALLY DEFERRED; the
        # deletes above queue their checks until commit, which would block
        # the ALTERs with "pending trigger events". Force the queue to run
        # now - every referencing row is gone or NULL, so it passes - then
        # restore deferred mode for the rest of the transaction.
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        cursor.execute("SET CONSTRAINTS ALL DEFERRED")

        # Drop every FK constraint referencing accounts_user (state targets
        # and shadows), then convert all state-target columns (empty or
        # all-NULL by now).
        for key, names in constraint_names.items():
            for name in names:
                cursor.execute(
                    sql.SQL("""ALTER TABLE {0} DROP CONSTRAINT {1}""").format(
                        sql.Identifier(key[0]), sql.Identifier(name)
                    )
                )
        for table, column, _, _ in targets:
            cursor.execute(
                sql.SQL(
                    """ALTER TABLE {0} ALTER COLUMN {1} TYPE uuid USING NULL::uuid"""
                ).format(sql.Identifier(table), sql.Identifier(column))
            )

        # Convert the PK itself (table is empty).
        cursor.execute(
            "ALTER TABLE accounts_user ALTER COLUMN id DROP IDENTITY IF EXISTS"
        )
        cursor.execute("ALTER TABLE accounts_user ALTER COLUMN id DROP DEFAULT")
        cursor.execute("DROP SEQUENCE IF EXISTS accounts_user_id_seq")
        cursor.execute("ALTER TABLE accounts_user DROP CONSTRAINT accounts_user_pkey")
        cursor.execute(
            "ALTER TABLE accounts_user ALTER COLUMN id TYPE uuid USING gen_random_uuid()"
        )
        cursor.execute("ALTER TABLE accounts_user ADD PRIMARY KEY (id)")

        # Re-add the FKs: model-correct ON DELETE action (SQL keywords
        # cannot be bound as parameters, so the two actions x deferrable
        # variants are literal templates), original constraint names, and
        # the DEFERRABLE state the database had before. Shadow tables get
        # no constraint back - their columns stay integer, inert legacy.
        for table, column, on_delete, _ in targets:
            name = pick_name((table, column))
            deferrable = deferrable_flags[(table, column)]
            if on_delete not in ("CASCADE", "SET NULL"):
                raise RuntimeError(
                    f"uuid_pk: unexpected on_delete {on_delete!r} on "
                    f"{table}.{column} - add a literal template for it"
                )
            if on_delete == "CASCADE" and deferrable:
                cursor.execute(
                    sql.SQL(
                        """ALTER TABLE {0} ADD CONSTRAINT {1} FOREIGN KEY ({2}) REFERENCES accounts_user(id) ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED"""
                    ).format(
                        sql.Identifier(table),
                        sql.Identifier(name),
                        sql.Identifier(column),
                    )
                )
            elif on_delete == "CASCADE":
                cursor.execute(
                    sql.SQL(
                        """ALTER TABLE {0} ADD CONSTRAINT {1} FOREIGN KEY ({2}) REFERENCES accounts_user(id) ON DELETE CASCADE"""
                    ).format(
                        sql.Identifier(table),
                        sql.Identifier(name),
                        sql.Identifier(column),
                    )
                )
            elif on_delete == "SET NULL" and deferrable:
                cursor.execute(
                    sql.SQL(
                        """ALTER TABLE {0} ADD CONSTRAINT {1} FOREIGN KEY ({2}) REFERENCES accounts_user(id) ON DELETE SET NULL DEFERRABLE INITIALLY DEFERRED"""
                    ).format(
                        sql.Identifier(table),
                        sql.Identifier(name),
                        sql.Identifier(column),
                    )
                )
            else:
                cursor.execute(
                    sql.SQL(
                        """ALTER TABLE {0} ADD CONSTRAINT {1} FOREIGN KEY ({2}) REFERENCES accounts_user(id) ON DELETE SET NULL"""
                    ).format(
                        sql.Identifier(table),
                        sql.Identifier(name),
                        sql.Identifier(column),
                    )
                )

    print(f"uuid_pk: converted {len(targets)} user FKs to uuid")


def from_uuid_pk(apps, schema_editor):
    # Irreversible in practice (uuid -> int is lossy); nothing to undo.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0002_retarget_user_fks"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(to_uuid_pk, from_uuid_pk),
            ],
            state_operations=[
                migrations.AlterField(
                    model_name="user",
                    name="id",
                    field=models.UUIDField(
                        primary_key=True,
                        default=uuid.uuid4,
                        editable=False,
                        serialize=False,
                    ),
                ),
            ],
        )
    ]
