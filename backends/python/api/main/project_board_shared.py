import logging
from typing import Any, Dict, List

from django.core.cache import cache
from django.db import connection

from .models import Bitrix24Account, ProjectCard, TimesheetItem
from .tenant_scoping import scope_to_tenant


logger = logging.getLogger(__name__)

PROJECT_STAGE_NEW = "Новый"
PROJECT_STAGE_ESTIMATE = "В просчете"
PROJECT_STAGE_IN_WORK = "В работе"
PROJECT_STAGE_NO_WRITEOFF_30 = "Нет списаний 1 месяц"
PROJECT_STAGE_NO_WRITEOFF_90 = "Нет списаний 3 месяца"
PROJECT_STAGE_SUCCESS = "Успех"
PROJECT_STAGE_FAILED = "Провал"

PROJECT_MANUAL_STAGES = [
    PROJECT_STAGE_NEW,
    PROJECT_STAGE_ESTIMATE,
    PROJECT_STAGE_IN_WORK,
    PROJECT_STAGE_SUCCESS,
    PROJECT_STAGE_FAILED,
]

PROJECT_AUTO_STAGES = [
    PROJECT_STAGE_NO_WRITEOFF_30,
    PROJECT_STAGE_NO_WRITEOFF_90,
]

PROJECT_STAGE_ORDER = [
    PROJECT_STAGE_NEW,
    PROJECT_STAGE_ESTIMATE,
    PROJECT_STAGE_IN_WORK,
    PROJECT_STAGE_NO_WRITEOFF_30,
    PROJECT_STAGE_NO_WRITEOFF_90,
    PROJECT_STAGE_SUCCESS,
    PROJECT_STAGE_FAILED,
]

PROJECT_CARD_TABLE_NAME = ProjectCard._meta.db_table
TIMESHEET_ITEM_TABLE_NAME = TimesheetItem._meta.db_table
PROJECT_CARD_SCHEMA_CACHE_KEY = "mainsoft:v2:project-card-schema-ready"
PROJECT_CARD_SCHEMA_TTL = 60
# Справочники (сотрудники/компании/юрлица) меняются редко, кэш — LocMemCache
# (CACHES не задан в settings.py -> дефолт Django), т.е. свой у каждого
# воркера gunicorn и полностью теряется при рестарте контейнера. Долгий TTL
# безопасен: у пользователя есть кнопка принудительного обновления
# (refreshReferenceOptions на фронте -> GET /api/project-board/meta?refresh=1
# -> ProjectCardService.get_meta(bypass_cache=True), см. views.py и задачу 4
# плана "справочники из локальной базы").
#
# Честная оговорка: кэш живёт в памяти процесса, а воркеров gunicorn
# несколько — форс-рефреш гарантированно пробивает кэш только того воркера,
# который принял именно этот запрос. Остальные воркеры продолжают отдавать
# старое значение до истечения TTL либо до собственного форс-рефреша.
BITRIX_REFERENCE_CACHE_TTL = 60 * 60 * 6
PROJECT_BOARD_CACHE_TTL = 60 * 2
HOMEPAGE_CACHE_TTL = 60 * 2
FILTER_EMPLOYEES_CACHE_SUFFIX = "filter-employees-v3"
USER_NAMES_CACHE_PREFIX = "user-names-v1"


def build_account_cache_key(account: Bitrix24Account, suffix: str) -> str:
    return f"mainsoft:v2:{account.pk}:{suffix}"


def invalidate_account_cache(account: Bitrix24Account, suffixes: List[str]) -> None:
    for suffix in suffixes:
        try:
            cache.delete(build_account_cache_key(account, suffix))
        except Exception as exc:
            logger.warning("Cache delete failed for %s: %s", suffix, exc)


def invalidate_project_runtime_caches(account: Bitrix24Account) -> None:
    """Сброс кэшей, которые протухают от наших же записей в проекты/списания.

    Здесь НЕТ "admin-company-directory" — намеренно, см.
    invalidate_company_directory_cache ниже.
    """
    invalidate_account_cache(
        account,
        [
            "filter-employees",
            FILTER_EMPLOYEES_CACHE_SUFFIX,
            "filter-projects",
            "project-board",
            "project-board-meta",
            "project-board-legal-entities",
            "project-board-homepage",
        ],
    )


def invalidate_company_directory_cache(account: Bitrix24Account) -> None:
    """Сброс кэша полного справочника компаний портала (ProjectCardService.
    get_full_company_directory, TTL 6 часов).

    Вынесено из invalidate_project_runtime_caches ОТДЕЛЬНО и зовётся только
    оттуда, где справочник действительно меняется — то есть после
    crm.company.add (ProjectCreationService.create). Причина в цене промаха:
    наполнение этого ключа — единственный в приложении полный постраничный
    обход компаний Битрикса (на боевом портале 23 252 компании: 465 страниц
    плюс столько же за реквизитами, 5-7 минут ожидания сети).

    Пока ключ стоял в общем списке, его сносил КАЖДЫЙ успешный синк таймшитов
    (views.timesheet_sync -> invalidate_project_runtime_caches), а следующий
    синк, создавший хоть одну карточку, платил за обход заново: шестичасовой
    TTL не доживал до второго использования. В проде это давало бимодальные
    синки — 4-6 секунд при попадании в кэш и 330-440 секунд при промахе, —
    и всё это время синк держал advisory-замок, отдавая 409 остальным
    сотрудникам портала (инцидент 31.08.2026).

    Синк таймшитов справочник компаний Битрикса не меняет, поэтому чистить
    его там было незачем.
    """
    invalidate_account_cache(account, ["admin-company-directory"])


def ensure_project_card_schema(force_refresh: bool = False) -> bool:
    if not force_refresh:
        cached = cache.get(PROJECT_CARD_SCHEMA_CACHE_KEY)
        if isinstance(cached, bool):
            return cached

    try:
        table_names = set(connection.introspection.table_names())
        if PROJECT_CARD_TABLE_NAME not in table_names or TIMESHEET_ITEM_TABLE_NAME not in table_names:
            is_available = False
        else:
            project_card_columns, timesheet_columns = _get_linkage_columns()

            # Board/sync features require linkage columns from migration 0009.
            if "project_item_id" not in project_card_columns or "project_item_id" not in timesheet_columns:
                _ensure_linkage_columns()
                project_card_columns, timesheet_columns = _get_linkage_columns()

            is_available = (
                "project_item_id" in project_card_columns
                and "project_item_id" in timesheet_columns
            )
    except Exception as exc:
        logger.warning("ProjectCard schema check failed: %s", exc)
        is_available = False

    cache.set(PROJECT_CARD_SCHEMA_CACHE_KEY, is_available, PROJECT_CARD_SCHEMA_TTL)
    return is_available


def _get_linkage_columns() -> tuple[set[str], set[str]]:
    with connection.cursor() as cursor:
        project_card_columns = {
            col.name for col in connection.introspection.get_table_description(cursor, PROJECT_CARD_TABLE_NAME)
        }
        timesheet_columns = {
            col.name for col in connection.introspection.get_table_description(cursor, TIMESHEET_ITEM_TABLE_NAME)
        }
    return project_card_columns, timesheet_columns


def _ensure_linkage_columns() -> None:
    """
    Hotfix path for schema drift in production: add missing linkage columns/indexes
    when migration step was skipped during release.
    """
    qn = connection.ops.quote_name
    project_table = qn(PROJECT_CARD_TABLE_NAME)
    timesheet_table = qn(TIMESHEET_ITEM_TABLE_NAME)
    project_col = qn("project_item_id")
    project_idx = qn(f"{PROJECT_CARD_TABLE_NAME}_project_item_id_idx")
    timesheet_idx = qn(f"{TIMESHEET_ITEM_TABLE_NAME}_project_item_id_idx")

    project_columns, timesheet_columns = _get_linkage_columns()

    sql_statements: List[str] = []
    if "project_item_id" not in project_columns:
        sql_statements.append(f"ALTER TABLE {project_table} ADD COLUMN {project_col} VARCHAR(50)")
    if "project_item_id" not in timesheet_columns:
        sql_statements.append(f"ALTER TABLE {timesheet_table} ADD COLUMN {project_col} VARCHAR(50)")
    # Index creation is idempotent with IF NOT EXISTS for PostgreSQL/SQLite.
    sql_statements.append(f"CREATE INDEX IF NOT EXISTS {project_idx} ON {project_table} ({project_col})")
    sql_statements.append(f"CREATE INDEX IF NOT EXISTS {timesheet_idx} ON {timesheet_table} ({project_col})")

    with connection.cursor() as cursor:
        for sql in sql_statements:
            cursor.execute(sql)

    if sql_statements:
        logger.warning(
            "Auto-healed missing project linkage columns/indexes in %s and %s",
            PROJECT_CARD_TABLE_NAME,
            TIMESHEET_ITEM_TABLE_NAME,
        )


def get_project_card_queryset(account: Bitrix24Account):
    if not ensure_project_card_schema():
        return ProjectCard.objects.none()
    return ProjectCard.objects.filter(**scope_to_tenant(account))


def build_local_project_groups(account: Bitrix24Account) -> List[Dict[str, Any]]:
    rows = (
        TimesheetItem.objects.filter(**scope_to_tenant(account))
        .exclude(project_id__isnull=True)
        .exclude(project_id="")
        .values("project_id", "project_title")
        .distinct()
    )

    items: List[Dict[str, Any]] = []
    seen_ids = set()

    for row in rows:
        project_id = str(row.get("project_id") or "").strip()
        project_name = str(row.get("project_title") or "").strip() or f"Проект {project_id}"
        if not project_id or project_id in seen_ids:
            continue
        seen_ids.add(project_id)
        items.append(
            {
                "ID": project_id,
                "NAME": project_name,
                "PROJECT": "Y",
                "CLOSED": "N",
            }
        )

    return items
