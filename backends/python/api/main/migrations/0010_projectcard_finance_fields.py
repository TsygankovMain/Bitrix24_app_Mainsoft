from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("main", "0009_project_sp_linkages"),
    ]

    operations = [
        migrations.AddField(
            model_name="projectcard",
            name="project_income",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="projectcard",
            name="project_expense",
            field=models.FloatField(blank=True, null=True),
        ),
    ]
