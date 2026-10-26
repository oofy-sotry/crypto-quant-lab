import getpass
from datetime import date, timedelta

from django.core.management.base import BaseCommand, CommandError

from market.models import Asset, ReprocessRun
from market.reprocess import retention_error, run_reprocess
from market.upbit import current_trading_day


class Command(BaseCommand):
    help = (
        "종목 하나의 기간을 재처리한다. 기본은 dry-run(무엇이 바뀔지만 보고 롤백)이고"
        " --apply를 줘야 반영한다. API와 달리 기간 상한이 없다."
    )

    def add_arguments(self, parser):
        parser.add_argument("--asset", required=True, help="종목 코드(예: KRW-BTC)")
        parser.add_argument("--target", required=True, choices=ReprocessRun.Target.values)
        parser.add_argument("--start", required=True, type=date.fromisoformat, help="UTC 날짜")
        parser.add_argument("--end", required=True, type=date.fromisoformat, help="포함")
        parser.add_argument("--reason", required=True, help="왜 재처리하는지 (이력에 남음)")
        parser.add_argument("--requested-by", default=getpass.getuser())
        parser.add_argument("--apply", action="store_true", help="실제로 반영")

    def handle(self, *args, **options):
        try:
            asset = Asset.objects.get(symbol=options["asset"])
        except Asset.DoesNotExist as exc:
            raise CommandError(f"없는 종목: {options['asset']}") from exc
        if options["start"] > options["end"]:
            raise CommandError("--start가 --end보다 늦습니다.")
        today = current_trading_day()
        if options["end"] >= today:
            # 진행 중인 날은 분봉·일봉 값이 아직 바뀐다(API와 같은 규칙).
            raise CommandError(f"--end는 마감된 날({today - timedelta(days=1)})까지만 가능합니다.")
        if error := retention_error(options["target"], options["start"], today):
            raise CommandError(error)

        run = run_reprocess(
            asset,
            options["target"],
            options["start"],
            options["end"],
            dry_run=not options["apply"],
            reason=options["reason"],
            requested_by=options["requested_by"],
        )

        mode = "dry-run (반영 안 함)" if run.dry_run else "실행"
        self.stdout.write(f"재처리 #{run.id} {asset.symbol} {run.target} {mode}: {run.status}")
        if run.status == ReprocessRun.Status.REJECTED:
            raise CommandError("같은 종목·기간의 재처리가 실행 중입니다.")
        if run.status == ReprocessRun.Status.FAILED:
            raise CommandError(run.error_message)

        self.stdout.write(
            f"  행 수 {run.rows_before:,} → {run.rows_after:,}, 바뀐 행 {run.changed_rows:,}"
        )
        for table, d in run.diff.items():
            if table == "checks":
                self.stdout.write(f"  재검증: {d}")
            else:
                counts = f"추가 {d['inserted']:,}, 변경 {d['updated']:,}, 삭제 {d['deleted']:,}"
                self.stdout.write(f"  {table}: {counts}")
