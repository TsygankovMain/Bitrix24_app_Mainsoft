from django.db import migrations


def forwards(apps, schema_editor):
    Portal = apps.get_model("main", "Portal")
    Bitrix24Account = apps.get_model("main", "Bitrix24Account")
    # Импортируем логику из portal_seed; она работает с любыми классами моделей,
    # включая historical (apps.get_model). Используем .update() — без вызова save,
    # чтобы избежать проблем с кастомным __init__ реальной модели.
    from main.portal_seed import seed_portals_from_accounts
    seed_portals_from_accounts(Portal, Bitrix24Account)


def backwards(apps, schema_editor):
    # Обратимо: снимаем связь аккаунтов и удаляем все Portal.
    # (Данные TimesheetItem/ProjectCard на этапе 0 ещё не привязаны к Portal.)
    Portal = apps.get_model("main", "Portal")
    Bitrix24Account = apps.get_model("main", "Bitrix24Account")
    Bitrix24Account.objects.update(portal=None)
    Portal.objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ("main", "0014_portal_and_nullable_fk"),
    ]
    operations = [
        migrations.RunPython(forwards, backwards),
    ]
