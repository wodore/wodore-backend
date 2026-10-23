"""Retarget user FK constraints from auth_user to accounts_user.

With swappable user FKs, Django never rewrites existing database
constraints when ``AUTH_USER_MODEL`` changes: databases created *before*
the switch keep FOREIGN KEY constraints pointing at the legacy
``auth_user`` table (which stays behind as an inert shadow), while fresh
databases get correct constraints from the start.

This migration finds every FK constraint referencing ``auth_user`` and
re-points it at ``accounts_user`` (pks were preserved by 0001, so
referential integrity holds throughout). On fresh databases it is a no-op.
"""

from django.db import migrations


RETARGET_QUERY = """
SELECT tc.table_name, tc.constraint_name, kcu.column_name
FROM information_schema.table_constraints tc
JOIN information_schema.key_column_usage kcu
  ON tc.constraint_name = kcu.constraint_name
 AND tc.constraint_schema = kcu.constraint_schema
JOIN information_schema.constraint_column_usage ccu
  ON tc.constraint_name = ccu.constraint_name
 AND tc.constraint_schema = ccu.constraint_schema
 AND ccu.table_name = 'auth_user'
WHERE tc.constraint_type = 'FOREIGN KEY'
  AND tc.table_schema = 'public'
"""


def retarget_user_fks(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return  # dev/test lanes and production are postgres; nothing else
    alias = schema_editor.connection.alias
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(RETARGET_QUERY)
        rows = cursor.fetchall()
    with schema_editor.connection.cursor() as cursor:
        for table, constraint, column in rows:
            cursor.execute(f'ALTER TABLE "{table}" DROP CONSTRAINT "{constraint}"')
            cursor.execute(
                f'ALTER TABLE "{table}" ADD CONSTRAINT "{constraint}" '
                f'FOREIGN KEY ("{column}") REFERENCES "accounts_user"("id") '
                f'DEFERRABLE INITIALLY DEFERRED'
            )
    if rows:
        print(f"retarget_user_fks: re-pointed {len(rows)} constraints to accounts_user")


def unretarget_user_fks(apps, schema_editor):
    # Reverse is not meaningful (the shadow table still exists and holds
    # the same pks); constraints pointing at accounts_user remain valid.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(retarget_user_fks, unretarget_user_fks),
    ]
