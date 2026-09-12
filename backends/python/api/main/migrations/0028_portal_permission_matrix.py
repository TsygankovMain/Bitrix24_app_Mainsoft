"""Редактируемые права ролей: матрица портала и журнал её изменений.

Номер 0028 — после 0027 покупки тарифа Pro (ProRequest).

Данных миграция не переносит и не должна: нет строки PortalPermissionMatrix =
матрица по умолчанию, то есть ровно те права, что действовали до миграции.
"""

import uuid

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('main', '0027_pro_purchase'),
    ]

    operations = [
        migrations.CreateModel(
            name='PortalPermissionMatrix',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('member_id', models.CharField(max_length=255, unique=True)),
                ('overrides', models.JSONField(blank=True, default=dict)),
                ('revision', models.PositiveIntegerField(default=0)),
                ('updated_by_id', models.CharField(blank=True, default='', max_length=50)),
                ('updated_by_name', models.CharField(blank=True, default='', max_length=255)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'db_table': 'portal_permission_matrix',
                'managed': True,
            },
        ),
        migrations.CreateModel(
            name='PortalPermissionChange',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('member_id', models.CharField(db_index=True, max_length=255)),
                ('revision', models.PositiveIntegerField(default=0)),
                ('changes', models.JSONField(blank=True, default=list)),
                ('matrix', models.JSONField(blank=True, default=dict)),
                ('changed_by_id', models.CharField(blank=True, default='', max_length=50)),
                ('changed_by_name', models.CharField(blank=True, default='', max_length=255)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'db_table': 'portal_permission_change',
                'ordering': ['-created_at'],
                'managed': True,
            },
        ),
    ]
