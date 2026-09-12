"""Печатная форма счёта: свои поля рядом с полями акта.

Зачем отдельные поля, а не переиспользование act_*: акт и печатная форма
счёта — два разных документа генератора с разными шаблонами и своими
ссылками. Один набор полей означал бы, что печать одного стирает ссылку на
другой, а бухгалтеру нужны оба файла одновременно.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("main", "0022_billing"),
    ]

    operations = [
        migrations.AddField(
            model_name="billingdocument",
            name="invoice_document_id",
            field=models.CharField(blank=True, default="", max_length=50),
        ),
        migrations.AddField(
            model_name="billingdocument",
            name="invoice_document_number",
            field=models.CharField(blank=True, default="", max_length=100),
        ),
        migrations.AddField(
            model_name="billingdocument",
            name="invoice_download_url",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="billingdocument",
            name="invoice_public_url",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="billingdocument",
            name="invoice_pdf_url",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="billingdocument",
            name="invoice_print_error",
            field=models.TextField(blank=True, default=""),
        ),
    ]
