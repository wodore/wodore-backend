# Generated manually for renaming symbol fields

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('categories', '0002_migrate_huttype_data'),
    ]

    operations = [
        migrations.RenameField(
            model_name='category',
            old_name='symbol',
            new_name='symbol_detailed',
        ),
        migrations.RenameField(
            model_name='category',
            old_name='icon',
            new_name='symbol_mono',
        ),
        migrations.AlterField(
            model_name='category',
            name='symbol_mono',
            field=models.ImageField(
                help_text='Monochrome symbol for UI elements',
                max_length=300,
                upload_to='categories/symbols/mono',
            ),
        ),
    ]
