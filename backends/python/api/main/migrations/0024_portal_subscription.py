"""Тариф портала (PortalSubscription) вместо выключателей на учётку.

Схема и перенос данных — в этой миграции, удаление старой таблицы
portal_feature — отдельной (0025): на PostgreSQL DROP таблицы, чьи внешние
ключи смотрят на portal, в одной транзакции со вставками в portal падает
на «pending trigger events». Логика переноса и правила свёртки строк —
main/pro_plan_migration.py.
"""

import uuid

import django.db.models.deletion
from django.db import migrations, models


def forwards(apps, schema_editor):
    from main.pro_plan_migration import copy_features_to_subscriptions

    copy_features_to_subscriptions(
        apps.get_model("main", "PortalFeature"),
        apps.get_model("main", "Bitrix24Account"),
        apps.get_model("main", "Portal"),
        apps.get_model("main", "PortalSubscription"),
        apps.get_model("main", "PortalSubscriptionEvent"),
    )


def backwards(apps, schema_editor):
    from main.pro_plan_migration import copy_subscriptions_to_features

    copy_subscriptions_to_features(
        apps.get_model("main", "PortalFeature"),
        apps.get_model("main", "Bitrix24Account"),
        apps.get_model("main", "PortalSubscription"),
    )


class Migration(migrations.Migration):

    dependencies = [
        ("main", "0023_billing_invoice_print"),
    ]

    operations = [
        migrations.CreateModel(
            name="PortalSubscription",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("plan", models.CharField(default="pro", max_length=32)),
                ("state", models.CharField(default="off", max_length=16)),
                ("paid_until", models.DateField(blank=True, null=True)),
                ("trial_until", models.DateField(blank=True, null=True)),
                ("price_month_rub", models.PositiveIntegerField(default=3000)),
                ("comment", models.TextField(blank=True, default="")),
                ("updated_by", models.CharField(blank=True, default="", max_length=255)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("portal", models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE, related_name="subscription", to="main.portal",
                )),
            ],
            options={
                "db_table": "portal_subscription",
                "managed": True,
                "indexes": [
                    models.Index(fields=["state", "paid_until"], name="portal_subscription_state_idx"),
                ],
            },
        ),
        migrations.CreateModel(
            name="PortalSubscriptionEvent",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("action", models.CharField(max_length=32)),
                ("changes", models.JSONField(blank=True, default=dict)),
                ("actor", models.CharField(blank=True, default="", max_length=255)),
                ("comment", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("subscription", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE, related_name="events",
                    to="main.portalsubscription",
                )),
            ],
            options={
                "db_table": "portal_subscription_event",
                "ordering": ["-created_at"],
                "managed": True,
            },
        ),
        migrations.RunPython(forwards, backwards),
    ]
