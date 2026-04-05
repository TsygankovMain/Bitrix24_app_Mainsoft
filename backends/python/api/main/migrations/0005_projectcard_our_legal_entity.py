from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('main', '0004_projectcard'),
    ]

    operations = [
        migrations.AddField(
            model_name='projectcard',
            name='our_legal_entity_id',
            field=models.CharField(blank=True, max_length=50, null=True),
        ),
        migrations.AddField(
            model_name='projectcard',
            name='our_legal_entity_name',
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
    ]
