from datetime import datetime, timedelta
from typing import Tuple

import jwt
import uuid

from b24pysdk import AbstractBitrixToken, BitrixApp, BitrixToken, Client
from b24pysdk.bitrix_api.credentials import OAuthPlacementData
from b24pysdk.bitrix_api.events import PortalDomainChangedEvent, OAuthTokenRenewedEvent
from b24pysdk.error import BitrixAPIError, BitrixValidationError
from b24pysdk.utils.functional import Classproperty

from django.db import models
from django.utils import timezone

from config import config


class Bitrix24Account(models.Model, AbstractBitrixToken):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    b24_user_id = models.IntegerField()
    is_b24_user_admin = models.BooleanField(default=False)
    # Когда флаг администратора последний раз сверялся с Bitrix (user.admin).
    # См. views._refresh_admin_flag: раньше сверка шла на КАЖДЫЙ /api/getToken,
    # то есть блокирующий REST-вызов на каждое монтирование страницы. Права
    # администратора меняются крайне редко, поэтому сверяем по TTL.
    admin_flag_checked_at = models.DateTimeField(null=True, blank=True)
    member_id = models.CharField(max_length=255)
    is_master_account = models.BooleanField(null=True)
    domain_url = models.CharField(max_length=255)
    status = models.CharField(max_length=50)
    application_token = models.CharField(max_length=255, null=True)
    created_at_utc = models.DateTimeField(auto_now_add=True)
    updated_at_utc = models.DateTimeField(auto_now=True)
    application_version = models.IntegerField()
    comment = models.TextField(null=True)
    access_token = models.CharField(max_length=255, null=True)
    refresh_token = models.CharField(max_length=255, null=True)
    expires = models.IntegerField(null=True)
    expires_in = models.IntegerField(null=True)
    current_scope = models.JSONField(null=True)
    portal = models.ForeignKey(
        "Portal", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="accounts", db_index=True,
    )
    last_timesheet_synced_at = models.DateTimeField(null=True, blank=True)
    sync_disabled_until = models.DateTimeField(null=True, blank=True)
    sync_failure_count = models.IntegerField(default=0)
    sync_failure_reason = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        managed = True
        db_table = "bitrix24account"
        unique_together = ("b24_user_id", "domain_url")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.portal_domain_changed_signal.connect(self.on_portal_domain_changed_event)
        self.oauth_token_renewed_signal.connect(self.on_oauth_token_renewed_event)

    @property
    def domain(self) -> str:
        return self.domain_url

    @domain.setter
    def domain(self, domain: str):
        self.domain_url = domain

    @property
    def auth_token(self) -> str:
        return self.access_token

    @auth_token.setter
    def auth_token(self, auth_token: str):
        self.access_token = auth_token

    @Classproperty
    def bitrix_app(cls) -> BitrixApp:
        return BitrixApp(client_id=config.client_id, client_secret=config.client_secret)

    @property
    def client(self) -> Client:
        return Client(self)

    def on_portal_domain_changed_event(self, _: PortalDomainChangedEvent):
        self.save(update_fields=["domain_url"])

    def on_oauth_token_renewed_event(self, event: OAuthTokenRenewedEvent):
        expires = event.renewed_oauth_token.oauth_token.expires
        # SDK обычно отдаёт expires как datetime (см. update_or_create_from_oauth_placement_data
        # ниже), но поле в модели — IntegerField (unix timestamp). Приводим устойчиво к обоим
        # случаям: datetime -> timestamp, число (int/float) оставляем как есть.
        self.expires = int(expires.timestamp()) if isinstance(expires, datetime) else expires
        self.expires_in = event.renewed_oauth_token.oauth_token.expires_in
        self.save(update_fields=["access_token", "refresh_token", "expires", "expires_in"])

    def create_jwt_token(self, minutes: int = 60) -> str:
        now_dt = timezone.now()

        payload = {
            "account_id": str(self.pk),
            "iat": now_dt,
            "exp": now_dt + timedelta(minutes=minutes),
        }

        return jwt.encode(payload, config.jwt_secret, algorithm=config.jwt_algorithm)

    @staticmethod
    def _validate_jwt_token(jwt_token: str) -> uuid.UUID:
        payload = jwt.decode(jwt_token, config.jwt_secret, algorithms=[config.jwt_algorithm])

        for key in ("account_id", "exp", "iat"):
            if key not in payload:
                raise BitrixValidationError("Invalid JWT token")

        return uuid.UUID(payload["account_id"])

    @classmethod
    def get_from_jwt_token(cls, jwt_token: str) -> "Bitrix24Account":
        account_uuid = cls._validate_jwt_token(jwt_token)
        return cls.objects.get(pk=account_uuid)

    @classmethod
    def update_or_create_from_oauth_placement_data(cls, oauth_placement_data: "OAuthPlacementData") -> Tuple["Bitrix24Account", bool]:
        """Create or update Bitrix24Account"""

        try:
            bitrix_token = BitrixToken.from_oauth_placement_data(oauth_placement_data, bitrix_app=cls.bitrix_app)
            app_info = bitrix_token.get_app_info().result
        except BitrixAPIError as error:
            raise BitrixValidationError(error.message) from error

        defaults = {
            "member_id": oauth_placement_data.member_id,
            "status": oauth_placement_data.status,
            "access_token": oauth_placement_data.oauth_token.access_token,
            "refresh_token": oauth_placement_data.oauth_token.refresh_token,
            "expires": int(oauth_placement_data.oauth_token.expires.timestamp()),
            "application_version": app_info.install.version,
        }

        bitrix24_account, is_created = cls.objects.update_or_create(
            domain_url=oauth_placement_data.domain,
            b24_user_id=app_info.user_id,
            defaults=defaults,
        )

        return bitrix24_account, is_created


class Portal(models.Model):
    """Tenant-сущность «компания» (этап 0 перестройки мультитенантности, спринт 4).

    Один Portal на каждый member_id Битрикс24. Общие данные компании: домен,
    статус. Данные (TimesheetItem/ProjectCard) на этапе 4 скоупятся по этому
    Portal, а не по Bitrix24Account (per-user). Пока (этапы 0-3) FK portal на
    данных nullable и переключение чтения за флагом USE_PORTAL_SCOPING.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    member_id = models.CharField(max_length=255, unique=True)
    domain_url = models.CharField(max_length=255, null=True, blank=True)
    status = models.CharField(max_length=50, default="active")
    created_at_utc = models.DateTimeField(auto_now_add=True)
    updated_at_utc = models.DateTimeField(auto_now=True)

    class Meta:
        managed = True
        db_table = "portal"
        indexes = [
            models.Index(fields=["member_id"], name="portal_member_id_idx"),
        ]

    def __str__(self) -> str:
        return f"Portal<{self.member_id}>"


class ApplicationInstallation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    status = models.CharField(max_length=50)
    created_at_utc = models.DateTimeField(auto_now_add=True)
    update_at_utc = models.DateTimeField(auto_now=True)
    bitrix_24_account = models.OneToOneField(Bitrix24Account, on_delete=models.CASCADE, db_column="bitrix_24_account_id")
    contact_person_id = models.UUIDField(null=True)
    bitrix_24_partner_contact_person_id = models.UUIDField(null=True)
    bitrix_24_partner_id = models.UUIDField(null=True)
    external_id = models.CharField(max_length=255, null=True)
    portal_license_family = models.CharField(max_length=255)
    portal_users_count = models.IntegerField(null=True)
    application_token = models.CharField(max_length=255, null=True)
    comment = models.TextField(null=True)
    status_code = models.JSONField(null=True)
    support_line_code = models.CharField(max_length=64, null=True, blank=True)
    support_line_dialog_id = models.CharField(max_length=255, null=True, blank=True)
    support_line_status = models.CharField(max_length=50, default="not_connected")
    support_line_error = models.TextField(null=True, blank=True)
    support_line_connected_at = models.DateTimeField(null=True, blank=True)


class TimesheetItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    bitrix24_account = models.ForeignKey(Bitrix24Account, on_delete=models.CASCADE, related_name="timesheets")
    portal = models.ForeignKey(
        "Portal", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="timesheets", db_index=True,
    )
    bitrix_id = models.IntegerField(db_index=True)
    task_id = models.CharField(max_length=50)
    employee_id = models.CharField(max_length=50)
    hours = models.FloatField()
    is_billable = models.BooleanField(default=False)
    non_billable_hours = models.FloatField(default=0.0)
    description = models.TextField(null=True, blank=True)
    project_id = models.CharField(max_length=50, null=True, blank=True)
    project_item_id = models.CharField(max_length=50, null=True, blank=True, db_index=True)
    hourly_rate_snapshot = models.FloatField(null=True, blank=True)
    project_title = models.CharField(max_length=255, null=True, blank=True)
    task_hierarchy_ids = models.JSONField(default=list)
    task_hierarchy_titles = models.JSONField(default=list)
    date_reflection = models.DateTimeField()
    source_created_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = True
        db_table = "timesheet_item"
        unique_together = ("bitrix24_account", "bitrix_id")
        indexes = [
            models.Index(fields=["bitrix24_account", "date_reflection"], name="timesheet_acc_date_idx"),
            models.Index(fields=["bitrix24_account", "employee_id", "date_reflection"], name="timesheet_acc_emp_date_idx"),
            models.Index(fields=["bitrix24_account", "project_id", "date_reflection"], name="timesheet_acc_proj_date_idx"),
            models.Index(fields=["bitrix24_account", "project_title", "date_reflection"], name="ts_acc_proj_ttl_dt_idx"),
            models.Index(fields=["bitrix24_account", "created_at", "bitrix_id"], name="timesheet_acc_created_idx"),
        ]


class ProjectCard(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    bitrix24_account = models.ForeignKey(Bitrix24Account, on_delete=models.CASCADE, related_name="project_cards")
    portal = models.ForeignKey(
        "Portal", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="project_cards", db_index=True,
    )
    project_item_id = models.CharField(max_length=50, null=True, blank=True, db_index=True)
    project_id = models.CharField(max_length=50, db_index=True)
    project_name = models.CharField(max_length=255)
    stage = models.CharField(max_length=50, db_index=True)
    manual_stage = models.CharField(max_length=50, null=True, blank=True)
    is_archived = models.BooleanField(default=False, db_index=True)
    archived_at = models.DateTimeField(null=True, blank=True)
    project_hours_budget = models.FloatField(null=True, blank=True)
    hourly_rate = models.FloatField(default=0.0)
    is_support = models.BooleanField(default=False)
    project_type = models.CharField(max_length=20, default="delivery")
    budget_mode = models.CharField(max_length=30, default="hours_and_amount")
    planned_budget_amount = models.FloatField(null=True, blank=True)
    curator_user_id = models.CharField(max_length=50, null=True, blank=True)
    curator_name = models.CharField(max_length=255, null=True, blank=True)
    project_start_date = models.DateField(null=True, blank=True)
    project_end_date = models.DateField(null=True, blank=True)
    company_id = models.CharField(max_length=50, null=True, blank=True)
    company_name = models.CharField(max_length=255, null=True, blank=True)
    our_legal_entity_id = models.CharField(max_length=50, null=True, blank=True)
    our_legal_entity_name = models.CharField(max_length=255, null=True, blank=True)
    last_writeoff_at = models.DateTimeField(null=True, blank=True, db_index=True)
    last_writeoff_days = models.IntegerField(default=0)
    stage_updated_at = models.DateTimeField(auto_now=True)
    stage_source = models.CharField(max_length=20, default="manual")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = True
        db_table = "project_card"
        unique_together = (
            ("bitrix24_account", "project_id"),
            ("bitrix24_account", "project_item_id"),
        )


class PortalUser(models.Model):
    """Локальная копия справочника пользователей Bitrix24 (Фаза 2 sync-offload).

    Кэш для user_map отчётов и /api/users вместо per-request user.get с
    LocMemCache (см. BitrixDataService.fetch_users). Хранит И активных, И
    неактивных сотрудников: user_map отчётов должен резолвить имя и по
    уволенным (историчные списания) — см. employee_ids.resolve_employee_name
    (используется в report_services для сборки user_map).
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    bitrix24_account = models.ForeignKey(Bitrix24Account, on_delete=models.CASCADE, related_name="portal_users")
    portal = models.ForeignKey(
        "Portal", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="portal_users", db_index=True,
    )
    bitrix_id = models.CharField(max_length=50, db_index=True)
    name = models.CharField(max_length=255, blank=True, default="")
    last_name = models.CharField(max_length=255, blank=True, default="")
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = True
        db_table = "portal_user"
        unique_together = ("bitrix24_account", "bitrix_id")
        indexes = [
            models.Index(fields=["bitrix24_account", "active"], name="portal_user_acc_active_idx"),
        ]


class PortalTask(models.Model):
    """Локальная копия справочника задач Bitrix24: актуальные название и группа.

    Зачем. Название задачи и её проект приложение НЕ вычисляет — оно копирует
    снимок, записанный на карточку списания в момент списания часов
    (DataProcessingService.normalize_items). Когда задачу переименовывают или
    переносят в другой проект, меняется ЗАДАЧА, а карточки списания не
    меняются: их updatedTime не двигается, поэтому инкрементальный синк их не
    видит, а ночная полная сверка перечитывает те же устаревшие поля с той же
    карточки. Само это не чинится никогда, ни при каком расписании.

    В цифрах прода на 31.08.2026: 57 задач несут больше одного названия
    (1 210 записей), 15 задач разошлись по разным проектам (100 записей).
    Пример: задача 4627 — 237 записей под именем «Тестирование системы
    Клеверенс.» и 23 под «ЗАДАЧИ ПО ООО ЭЛР» после переименования.

    Отсюда таблица: один источник актуальной правды на портал. Отчёты берут
    название и проект отсюда, а снимок в timesheet_item остаётся нетронутым
    как след «под чем списывалось». Резолв идёт НА ЧТЕНИИ, поэтому вся история
    становится актуальной сразу, без миграции данных.

    Закрытые периоды защищать здесь не нужно: закрытие сделано правами
    Битрикса и распространяется и на задачи, и на проекты — перенести задачу
    в закрытом периоде попросту нельзя.

    group_id — это GROUP_ID задачи, то есть рабочая группа Битрикса. Он же
    project_id в наших карточках проектов и в timesheet_item: подтверждено
    сверкой на проде (25 = ИТ-ЛАБ, 415 = ПВД сопровождение, 425 = ВСС) и
    косвенно тем, что словарь в report_queries.build_project_title_lookups
    называется by_group.

    Устройство один в один как у PortalUser (см. его докстринг): та же пара
    ключей, та же уникальность, тот же фоновый скоуп в sync_all_portals.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    bitrix24_account = models.ForeignKey(Bitrix24Account, on_delete=models.CASCADE, related_name="portal_tasks")
    portal = models.ForeignKey(
        "Portal", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="portal_tasks", db_index=True,
    )
    bitrix_id = models.CharField(max_length=50, db_index=True)
    title = models.CharField(max_length=500, blank=True, default="")
    group_id = models.CharField(max_length=50, blank=True, default="", db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = True
        db_table = "portal_task"
        unique_together = ("bitrix24_account", "bitrix_id")
        indexes = [
            models.Index(fields=["bitrix24_account", "group_id"], name="portal_task_acc_group_idx"),
        ]


class ClosedPeriod(models.Model):
    """Закрытый месяц: часы за него заморожены и правке не подлежат.

    Отчёт по часам — основание для счёта клиенту. Пока месяц открыт, его цифры
    могут поехать: сотрудник допишет часы задним числом, кто-то перенесёт
    задачу в другой проект, и приложение честно перепишет проект во всех её
    карточках (механизм от 31.08.2026). После выставления акта это
    недопустимо.

    Гранулярность — ПОРТАЛ ЦЕЛИКОМ (решение заказчика 31.08.2026): закрыли
    август — закрыт у всех проектов и сотрудников. Закрытие по проектам
    отдельно обсуждалось и отклонено как резко усложняющее и отчёты, и
    правило «что делать с задачей, переехавшей из закрытого проекта в
    открытый».

    Признак закрытости на самой записи НЕ заводим: он разъедется с этой
    таблицей при первом же переоткрытии. Запись считается закрытой, если её
    date_reflection попадает в закрытый период — вычисляется на лету.

    Опоздавшие часы определяются сравнением source_created_at записи с
    closed_at её периода. Отдельного поля тоже не нужно.

    Переоткрытие обязано существовать (первая же ошибка иначе становится
    катастрофой) и обязано объясняться: reopen_reason заполняется всегда,
    поля переоткрытия — журнал события, а не рутина.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    bitrix24_account = models.ForeignKey(
        Bitrix24Account, on_delete=models.CASCADE, related_name="closed_periods",
    )
    portal = models.ForeignKey(
        "Portal", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="closed_periods", db_index=True,
    )
    year = models.IntegerField()
    month = models.IntegerField()

    closed_at = models.DateTimeField()
    closed_by = models.CharField(max_length=50, blank=True, default="")
    closed_by_name = models.CharField(max_length=255, blank=True, default="")

    # Снимок объёма на момент закрытия — для сверки «столько мы заморозили».
    # Пересчитывать его потом бессмысленно: данные могли измениться.
    stats = models.JSONField(default=dict, blank=True)

    reopened_at = models.DateTimeField(null=True, blank=True)
    reopened_by = models.CharField(max_length=50, blank=True, default="")
    reopened_by_name = models.CharField(max_length=255, blank=True, default="")
    reopen_reason = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = True
        db_table = "closed_period"
        unique_together = ("bitrix24_account", "year", "month")
        ordering = ["-year", "-month"]
        indexes = [
            models.Index(fields=["bitrix24_account", "year", "month"], name="closed_period_acc_ym_idx"),
        ]

    def __str__(self):
        return f"{self.year}-{self.month:02d}"

    @property
    def is_open(self) -> bool:
        """Переоткрытый период снова открыт: строка остаётся как журнал."""
        return self.reopened_at is not None


class RequestLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    timestamp = models.DateTimeField(auto_now_add=True)
    method = models.CharField(max_length=10)
    path = models.TextField()
    status_code = models.IntegerField(null=True)
    duration_ms = models.FloatField(null=True)
    request_body = models.TextField(null=True)
    response_body = models.TextField(null=True)
    error_message = models.TextField(null=True)
    bitrix24_account = models.ForeignKey(
        "Bitrix24Account",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        db_index=True,
        related_name="+",
    )

    class Meta:
        managed = True
        db_table = "request_log"
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["timestamp"], name="request_log_ts_idx"),
        ]


class SystemLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    timestamp = models.DateTimeField(auto_now_add=True)
    level = models.CharField(max_length=20)  # INFO, ERROR, WARNING
    module = models.CharField(max_length=100)
    message = models.TextField()
    traceback = models.TextField(null=True)
    bitrix24_account = models.ForeignKey(
        "Bitrix24Account",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        db_index=True,
        related_name="+",
    )

    class Meta:
        managed = True
        db_table = "system_log"
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["timestamp"], name="system_log_ts_idx"),
        ]


class SyncRun(models.Model):
    """Журнал запусков фоновой синхронизации по расписанию (задача 3.6)."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    scope = models.CharField(max_length=20, default="timesheet")  # timesheet | project | all
    status = models.CharField(max_length=20, default="running")   # running|success|partial|error
    portals_total = models.IntegerField(default=0)
    portals_synced = models.IntegerField(default=0)
    items_synced = models.IntegerField(default=0)
    window_days = models.IntegerField(default=7)
    error_summary = models.TextField(null=True, blank=True)

    class Meta:
        managed = True
        db_table = "sync_run"
        ordering = ["-started_at"]
        indexes = [
            models.Index(fields=["started_at"], name="sync_run_started_idx"),
        ]


class PortalSubscription(models.Model):
    """Тариф портала: единственный источник правды о платных функциях.

    Ключ — ПОРТАЛ (Portal, уникален по member_id), а не учётка. Прежняя
    модель PortalFeature висела на Bitrix24Account — записи на сотрудника, —
    и команда включения писала строку каждой учётке: сотрудник, впервые
    открывший приложение после включения, оставался без функции. Домен ключом
    тоже не годится: у порталов он меняется, member_id — нет.

    Хранится ТОЛЬКО на нашем сервере. Писать по REST нельзя ни при каких
    условиях (app.option пишется токеном приложения из консоли браузера) —
    только командой pro_plan (main/management/commands/pro_plan.py).

    Поле state — решение оператора, а не итог. Итог (действует, грейс,
    истёк) вычисляется при каждом чтении по датам — billing_features.
    resolve_subscription — поэтому неоплаченный портал закрывается сам, без
    ночной задачи и без ручного действия:

    - active: оплачено по paid_until включительно (None — бессрочно, так
      перенесены прежние state=on без срока), затем GRACE_DAYS дней грейса,
      затем «только чтение»;
    - trial: пробный до trial_until включительно (None — бессрочный тест),
      затем «только чтение» сразу, без грейса;
    - expired: «только чтение» сразу, без ожидания дат (оператор закрыл
      запись сам);
    - off: функций нет совсем.

    Какие функции входят в тариф — billing_features.PLAN_FEATURES.
    """

    PLAN_PRO = "pro"
    PLANS = (PLAN_PRO,)

    STATE_ACTIVE = "active"
    STATE_TRIAL = "trial"
    STATE_EXPIRED = "expired"
    STATE_OFF = "off"
    STATES = (STATE_ACTIVE, STATE_TRIAL, STATE_EXPIRED, STATE_OFF)

    DEFAULT_PRICE_MONTH_RUB = 3000

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    portal = models.OneToOneField(
        Portal, on_delete=models.CASCADE, related_name="subscription",
    )
    plan = models.CharField(max_length=32, default=PLAN_PRO)
    state = models.CharField(max_length=16, default=STATE_OFF)
    # Даты, а не моменты: «оплачено по 31.10» — это весь день 31.10 по
    # Москве (billing_features.subscription_today), а не полночь UTC.
    paid_until = models.DateField(null=True, blank=True)
    trial_until = models.DateField(null=True, blank=True)
    price_month_rub = models.PositiveIntegerField(default=DEFAULT_PRICE_MONTH_RUB)
    comment = models.TextField(blank=True, default="")
    updated_by = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = True
        db_table = "portal_subscription"
        indexes = [
            models.Index(fields=["state", "paid_until"], name="portal_subscription_state_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.plan}={self.state}"


class PortalSubscriptionEvent(models.Model):
    """Журнал изменений тарифа: кто, когда и что поменял.

    Нужен не для красоты: спор «мы платили до ноября» решается только
    историей, а поле updated_by помнит лишь последнего.
    changes — {поле: [было, стало]} строками.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    subscription = models.ForeignKey(
        PortalSubscription, on_delete=models.CASCADE, related_name="events",
    )
    action = models.CharField(max_length=32)
    changes = models.JSONField(default=dict, blank=True)
    actor = models.CharField(max_length=255, blank=True, default="")
    comment = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = True
        db_table = "portal_subscription_event"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.action}@{self.created_at:%Y-%m-%d}"


class BillingDocument(models.Model):
    """Выставленный документ: счёт в CRM + его снимок у нас.

    Почему снимок, а не ссылка на списания: списание уникально по паре
    «учётка + bitrix_id» (при USE_PORTAL_SCOPING=False у каждого сотрудника
    своя копия строки), а синхронизация физически удаляет записи, пропавшие
    в Битриксе (timesheet_sync_service). Ссылаться на TimesheetItem.pk
    нельзя — документ хранит собственные часы, ставку и сумму и помнит
    списание только по bitrix_id.

    Черновиков нет: статусы ровно два — issued и cancelled. Документ ничего
    не пересчитывает после выставления; расхождения с текущими списаниями
    показываются как drift на карточке.
    """

    STATUS_ISSUED = "issued"
    STATUS_CANCELLED = "cancelled"

    VAT_INCLUDED = "included"
    VAT_NONE = "none"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    bitrix24_account = models.ForeignKey(
        Bitrix24Account, on_delete=models.CASCADE, related_name="billing_documents",
    )
    portal = models.ForeignKey(
        "Portal", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="billing_documents", db_index=True,
    )

    status = models.CharField(max_length=16, default=STATUS_ISSUED, db_index=True)
    period_from = models.DateField(null=True, blank=True)
    period_to = models.DateField(null=True, blank=True)

    company_id = models.CharField(max_length=50, blank=True, default="")
    company_name = models.CharField(max_length=255, blank=True, default="")
    our_company_id = models.CharField(max_length=50, blank=True, default="")
    our_company_name = models.CharField(max_length=255, blank=True, default="")

    currency = models.CharField(max_length=10, default="RUB")
    vat_mode = models.CharField(max_length=16, default=VAT_INCLUDED)
    vat_rate = models.FloatField(default=0.0)

    total_hours = models.FloatField(default=0.0)
    total_amount = models.FloatField(default=0.0)

    # Снимок параметров отбора: чем документ собран. Нужен карточке и
    # переоформлению («отменить и выставить тем же фильтром»), пересчётом
    # документа он не управляет никогда.
    grouping = models.CharField(max_length=16, default="project")
    filter_snapshot = models.JSONField(default=dict, blank=True)

    crm_entity_id = models.CharField(max_length=50, blank=True, default="")
    crm_account_number = models.CharField(max_length=100, blank=True, default="")

    act_document_id = models.CharField(max_length=50, blank=True, default="")
    act_number = models.CharField(max_length=100, blank=True, default="")
    # Ссылки генератора документов: без них напечатанный акт некуда отдать.
    # В контракте их нет, но контракт перечисляет модель, а не запрещает
    # хранить результат вызова, который сам же предписывает делать.
    act_download_url = models.TextField(blank=True, default="")
    act_public_url = models.TextField(blank=True, default="")
    act_pdf_url = models.TextField(blank=True, default="")
    act_error = models.TextField(blank=True, default="")

    # Печатная форма САМОГО счёта (шаблон «Счет (Россия)» и подобные) —
    # отдельный документ генератора, не путать с crm_entity_id (это сам
    # смарт-счёт в CRM) и не путать с актом. Бухгалтер отправляет клиенту
    # пару «счёт + акт», и обе половины должны быть доступны из карточки
    # документа приложения, а не из двух разных мест.
    invoice_document_id = models.CharField(max_length=50, blank=True, default="")
    invoice_document_number = models.CharField(max_length=100, blank=True, default="")
    invoice_download_url = models.TextField(blank=True, default="")
    invoice_public_url = models.TextField(blank=True, default="")
    invoice_pdf_url = models.TextField(blank=True, default="")
    invoice_print_error = models.TextField(blank=True, default="")

    created_by_id = models.CharField(max_length=50, blank=True, default="")
    created_by_name = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by_id = models.CharField(max_length=50, blank=True, default="")
    cancelled_by_name = models.CharField(max_length=255, blank=True, default="")
    cancel_reason = models.TextField(blank=True, default="")

    class Meta:
        managed = True
        db_table = "billing_document"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["bitrix24_account", "status"], name="billing_doc_acc_status_idx"),
            models.Index(fields=["bitrix24_account", "company_id"], name="billing_doc_acc_comp_idx"),
            models.Index(fields=["bitrix24_account", "period_from"], name="billing_doc_acc_period_idx"),
        ]

    def __str__(self) -> str:
        return f"BillingDocument<{self.crm_account_number or self.pk}>"

    @property
    def is_issued(self) -> bool:
        return self.status == self.STATUS_ISSUED


class BillingLine(models.Model):
    """Строка документа: то, что уходит товарной строкой в счёт CRM.

    По умолчанию одна строка на проект, количество — в часах. Сумма строки
    считается как сумма сумм её списаний, а не как round(часы × ставка):
    ставка внутри строки может быть разной (ставку помнит каждое списание),
    и пересчёт от общего количества часов разошёлся бы с детализацией.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    document = models.ForeignKey(
        BillingDocument, on_delete=models.CASCADE, related_name="lines",
    )
    project_id = models.CharField(max_length=50, blank=True, default="")
    project_name = models.CharField(max_length=255, blank=True, default="")
    title = models.CharField(max_length=500, blank=True, default="")
    hours = models.FloatField(default=0.0)
    rate = models.FloatField(default=0.0)
    amount = models.FloatField(default=0.0)
    sort = models.IntegerField(default=0)

    class Meta:
        managed = True
        db_table = "billing_line"
        ordering = ["sort", "id"]


class BillingEntry(models.Model):
    """Потреблённое списание: снимок часов, ставки и суммы на момент выставления.

    ЗАЧЕМ is_active — денормализация статуса документа.

    Контракт требует частичный уникальный индекс
    (bitrix24_account, timesheet_bitrix_id) с условием «документ действует»:
    одно списание не может попасть в два действующих документа, и защищать
    это должна БАЗА, а не проверка в коде — два бухгалтера, нажавшие
    «Выставить» одновременно, проверку в коде обходят.

    В Django частичный уникальный индекс — это UniqueConstraint(condition=Q(...)),
    но условие Q может ссылаться только на поля САМОЙ модели: выразить
    document__status='issued' в condition нельзя (Django отвергает join в
    условии индекса, да и СУБД такого индекса не построит — индекс строится
    по одной таблице). Поэтому статус документа продублирован здесь полем
    is_active, а индекс строится по нему.

    Поле поддерживает СЕРВИС (billing_service): выставление создаёт записи с
    is_active=True, отмена документа переводит все его записи в False одним
    UPDATE в той же транзакции. Ручная правка статуса документа мимо сервиса
    рассинхронизирует пару — этого делать нельзя.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    document = models.ForeignKey(
        BillingDocument, on_delete=models.CASCADE, related_name="entries",
    )
    line = models.ForeignKey(
        BillingLine, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="entries",
    )
    bitrix24_account = models.ForeignKey(
        Bitrix24Account, on_delete=models.CASCADE, related_name="billing_entries",
    )
    portal = models.ForeignKey(
        "Portal", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="billing_entries", db_index=True,
    )

    timesheet_bitrix_id = models.IntegerField()
    is_active = models.BooleanField(default=True)

    employee_id = models.CharField(max_length=50, blank=True, default="")
    employee_name = models.CharField(max_length=255, blank=True, default="")
    date_reflection = models.DateTimeField(null=True, blank=True)
    hours = models.FloatField(default=0.0)
    rate_snapshot = models.FloatField(default=0.0)
    amount = models.FloatField(default=0.0)
    project_id = models.CharField(max_length=50, blank=True, default="")
    project_name = models.CharField(max_length=255, blank=True, default="")
    task_id = models.CharField(max_length=50, blank=True, default="")
    task_title = models.CharField(max_length=500, blank=True, default="")
    description = models.TextField(blank=True, default="")

    class Meta:
        managed = True
        db_table = "billing_entry"
        indexes = [
            models.Index(fields=["bitrix24_account", "timesheet_bitrix_id"], name="billing_entry_acc_ts_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["bitrix24_account", "timesheet_bitrix_id"],
                condition=models.Q(is_active=True),
                name="billing_entry_one_active_per_timesheet",
            ),
        ]
