from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("main", "0009_project_sp_linkages"),
    ]

    operations = [
        migrations.AddField(
            model_name="projectcard",
            name="project_type",
            field=models.CharField(default="delivery", max_length=20),
        ),
        migrations.AddField(
            model_name="projectcard",
            name="budget_mode",
            field=models.CharField(default="hours_and_amount", max_length=30),
        ),
        migrations.AddField(
            model_name="projectcard",
            name="planned_budget_amount",
            field=models.FloatField(blank=True, null=True),
        ),
    ]
