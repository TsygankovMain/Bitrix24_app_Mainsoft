from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("main", "0008_log_timestamp_indexes"),
    ]

    operations = [
        migrations.AddField(
            model_name="timesheetitem",
            name="project_item_id",
            field=models.CharField(blank=True, db_index=True, max_length=50, null=True),
        ),
        migrations.AddField(
            model_name="projectcard",
            name="project_item_id",
            field=models.CharField(blank=True, db_index=True, max_length=50, null=True),
        ),
        migrations.AlterUniqueTogether(
            name="projectcard",
            unique_together={("bitrix24_account", "project_id"), ("bitrix24_account", "project_item_id")},
        ),
    ]
