from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('main', '0030_pro_request_crm_task_id'),
    ]

    operations = [
        migrations.AddField(
            model_name='portal',
            name='placements_handler_url',
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
    ]
