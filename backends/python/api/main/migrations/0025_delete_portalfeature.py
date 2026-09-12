"""Удаление portal_feature: данные перенесены в portal_subscription (0024).

Откат пересоздаёт пустую таблицу, а обратный шаг 0024 заполняет её из
действующих тарифов — выкат можно откатить, не выключив клиентов.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("main", "0024_portal_subscription"),
    ]

    operations = [
        migrations.DeleteModel(
            name="PortalFeature",
        ),
    ]
