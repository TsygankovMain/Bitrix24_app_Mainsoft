"""Ролевая модель: роли сотрудников портала и отметка переноса «Бухгалтерии».

Номер 0026 — после 0024/0025 тарифа Pro (PortalSubscription). Если ветки
вливаются в другом порядке, может понадобиться merge-миграция.

Данных миграция не переносит, и это не упущение: прежний список
billing_accountants лежит в app.option каждого портала, а не в нашей БД.
Перенос ленивый — при первой проверке прав на портале
(main/roles.py, ensure_accountants_imported), с отметкой в PortalRoleState.
"""

import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('main', '0025_delete_portalfeature'),
    ]

    operations = [
        migrations.CreateModel(
            name='PortalRoleState',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('member_id', models.CharField(max_length=255, unique=True)),
                ('accountants_imported_at', models.DateTimeField(blank=True, null=True)),
                ('imported_user_ids', models.JSONField(blank=True, default=list)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'db_table': 'portal_role_state',
                'managed': True,
            },
        ),
        migrations.CreateModel(
            name='PortalRole',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('member_id', models.CharField(db_index=True, max_length=255)),
                ('b24_user_id', models.CharField(max_length=50)),
                ('role', models.CharField(max_length=32)),
                ('assigned_by_id', models.CharField(blank=True, default='', max_length=50)),
                ('assigned_by_name', models.CharField(blank=True, default='', max_length=255)),
                ('source', models.CharField(blank=True, default='manual', max_length=32)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('portal', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='portal_roles', to='main.portal')),
            ],
            options={
                'db_table': 'portal_role',
                'managed': True,
                'unique_together': {('member_id', 'b24_user_id')},
            },
        ),
    ]
