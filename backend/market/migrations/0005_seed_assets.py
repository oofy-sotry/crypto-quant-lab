from django.db import migrations

ASSETS = [
    ("KRW-BTC", "비트코인"),
    ("KRW-ETH", "이더리움"),
    ("KRW-XRP", "리플"),
    ("KRW-SOL", "솔라나"),
    ("KRW-DOGE", "도지코인"),
]


def seed(apps, schema_editor):
    Asset = apps.get_model("market", "Asset")
    for symbol, name in ASSETS:
        Asset.objects.get_or_create(symbol=symbol, defaults={"name": name})


def unseed(apps, schema_editor):
    Asset = apps.get_model("market", "Asset")
    Asset.objects.filter(symbol__in=[symbol for symbol, _ in ASSETS]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("market", "0004_integrityissue"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
