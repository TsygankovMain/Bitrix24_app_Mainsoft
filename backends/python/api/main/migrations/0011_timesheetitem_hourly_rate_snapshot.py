from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("main", "0010_projectcard_budget_foundation"),
    ]

    operations = [
        migrations.AddField(
            model_name="timesheetitem",
            name="hourly_rate_snapshot",
            field=models.FloatField(blank=True, null=True),
        ),
    ]
