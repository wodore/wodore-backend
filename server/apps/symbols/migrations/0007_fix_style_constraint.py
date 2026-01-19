from django.db import migrations

class Migration(migrations.Migration):
    dependencies = [
        ("symbols", "0006_fix_style_column_length"),
    ]

    operations = [
        migrations.RunSQL(
            """
            ALTER TABLE symbols_symbol DROP CONSTRAINT IF EXISTS symbols_symbol_style_valid;
            ALTER TABLE symbols_symbol ADD CONSTRAINT symbols_symbol_style_valid
                CHECK (style IN ('detailed', 'simple', 'mono', 'outlined', 'filled', 'outlined-mono',
                                 'detailed-animated', 'simple-animated', 'mono-animated',
                                 'outlined-animated', 'filled-animated'));
            """,
            """
            ALTER TABLE symbols_symbol DROP CONSTRAINT IF EXISTS symbols_symbol_style_valid;
            ALTER TABLE symbols_symbol ADD CONSTRAINT symbols_symbol_style_valid
                CHECK (style IN ('detailed', 'simple', 'mono'));
            """
        ),
    ]
