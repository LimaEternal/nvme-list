"""
fio-test.py — Автоматический бенчмаркинг несистемных накопителей.

Сканирует систему на несистемные диски, классифицирует их по интерфейсу
(NVMe/SAS/SATA), запускает FIO-тесты с оптимальными параметрами для каждого типа
и выводит результаты в реальном времени через rich, а по завершении — в MD-отчёт.

Использование:
    python fio-test.py
    python fio-test.py --precond
    python fio-test.py --output report.md
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

from rich.console import Console
from rich.live import Live
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
)
from rich.table import Table

from configs import nvme, sas, sata
from utils.reporter import generate_report
from utils.scanner import get_non_system_disks

console = Console()

INTERFACE_CONFIGS = {
    "NVME": nvme.TESTS,
    "SAS": sas.TESTS,
    "SATA": sata.TESTS,
}

INTERFACE_DESCRIPTIONS = {
    "NVME": nvme.DESCRIPTION,
    "SAS": sas.DESCRIPTION,
    "SATA": sata.DESCRIPTION,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Автоматический бенчмаркинг несистемных накопителей (FIO)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Примеры:\n"
            "  python fio-test.py                  — базовое тестирование\n"
            "  python fio-test.py --precond         — с прекондишнингом\n"
            "  python fio-test.py --output my.md    — свой путь для отчёта\n"
            "  python fio-test.py --yes             — без запроса подтверждения\n"
        ),
    )

    parser.add_argument(
        "--precond",
        action="store_true",
        help=(
            "Выполнить прекондишнинг (запись 100%% объёма диска перед тестами). "
            "Стабилизирует производительность SSD, но затирает все данные. "
            "Запись идёт блоком bs=1M напрямую на устройство (--direct=1)."
        ),
    )

    parser.add_argument(
        "--yes", "-y",
        action="store_true",
        help="Пропустить запрос подтверждения (для автоматизации на стенде)",
    )

    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Путь для MD-отчёта (по умолчанию: fio_report_<timestamp>.md)",
    )

    parser.add_argument(
        "--runtime",
        type=int,
        default=30,
        help="Длительность каждого теста в секундах (по умолчанию: 30)",
    )

    return parser.parse_args()


def run_fio_test(disk_info: dict, test_id: str, base_args: list[str]) -> dict:
    """Запускает один подтест FIO и парсит JSON-результат."""
    disk_path = disk_info["path"]
    sector_size = disk_info["phy_sec"]

    fio_args = list(base_args)

    if sector_size == 4096:
        if "rand" in test_id:
            fio_args = [
                a if not a.startswith("--bs=") else "--bs=4k" for a in fio_args
            ]
        elif "seq" in test_id:
            fio_args = [
                a if not a.startswith("--bs=") else "--bs=128k" for a in fio_args
            ]

    cmd = [
        "fio",
        f"--name={test_id}",
        f"--filename={disk_path}",
        "--direct=1",
        "--ioengine=libaio",
        "--group_reporting",
        "--norandommap",
        "--output-format=json",
    ] + fio_args

    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        return {"error": f"FIO Error (exit {res.returncode})"}

    try:
        fio_data = json.loads(res.stdout)
        job = fio_data["jobs"][0]

        mode = "read" if "read" in test_id else "write"
        stats = job[mode]

        avg_lat = stats["lat_ns"]["mean"] / 1_000_000
        p99_lat = stats["clat_ns"]["percentile"]["99.000000"] / 1_000_000

        return {
            "iops": int(stats["iops"]),
            "bw_mb": round(stats["bw"] / 1024, 2),
            "lat_avg": round(avg_lat, 2),
            "lat_p99": round(p99_lat, 2),
        }
    except Exception as e:
        return {"error": f"Parse Error: {e}"}


def run_precondition(disk_info: dict) -> bool:
    """Выполняет прекондишнинг — запись 100% объёма диска."""
    cmd = [
        "fio",
        f"--name=precond",
        f"--filename={disk_info['path']}",
        "--size=100%",
        "--rw=write",
        "--bs=1M",
        "--direct=1",
        "--ioengine=libaio",
        "--numjobs=1",
        "--iodepth=32",
        "--group_reporting",
    ]

    res = subprocess.run(cmd, capture_output=True, text=True)
    return res.returncode == 0


def build_table(results: list[dict]) -> Table:
    """Строит Rich-таблицу с результатами."""
    table = Table(
        title="[bold green]Результаты тестирования накопителей (FIO)[/bold green]",
        show_lines=True,
    )

    table.add_column("Диск", style="cyan")
    table.add_column("Модель / Серийник", style="magenta")
    table.add_column("Интерфейс / Объём")
    table.add_column("Профиль теста", style="yellow")
    table.add_column("IOPS", justify="right", style="green")
    table.add_column("Скорость (МБ/с)", justify="right", style="green")
    table.add_column("Lat Avg (мс)", justify="right")
    table.add_column("Lat p99 (мс)", justify="right")

    for r in results:
        table.add_row(
            r["disk"],
            f"{r['model']}\n[grey50]SN: {r['serial']}[/grey50]",
            f"{r['tran']} (Sector: {r['sector']}B)\n[grey50]{r['size']}[/grey50]",
            r["test_name"],
            str(r["iops"]),
            str(r["bw"]),
            str(r["lat_avg"]),
            str(r["lat_p99"]),
        )

    return table


def confirm_destruction(disks: list[dict], use_precond: bool, force: bool) -> None:
    """
    Предупреждает о потере данных и запрашивает подтверждение.

    Тесты write на блочном устройстве уничтожают данные без возможности
    восстановления. Пользователь должен явно подтвердить запуск.
    """
    console.print()
    console.print("[bold red]═══════════════════════════════════════════════════════════[/bold red]")
    console.print("[bold red]  ВНИМАНИЕ: ТЕСТИРОВАНИЕ УНИЧТОЖИТ ДАННЫЕ НА ДИСКАХ[/bold red]")
    console.print("[bold red]═══════════════════════════════════════════════════════════[/bold red]")
    console.print()
    console.print("[bold red]FIO записывает напрямую в блочные устройства (/dev/*).[/bold red]")
    console.print("[bold red]Тесты seq_write и rand_write перезапишут данные на дисках.[/bold red]")
    console.print("[bold red]Восстановление данных будет невозможным![/bold red]")

    if use_precond:
        console.print()
        console.print("[bold red]Плюс: прекондишнинг запишет 100% объёма каждого диска![/bold red]")

    console.print()
    console.print("[yellow]Целевые диски:[/yellow]")

    for d in disks:
        console.print(
            f"  [cyan]/dev/{d['name']}[/cyan] — {d['model']} "
            f"({d['tran']}, {d['size']})"
        )

    console.print()

    if force:
        console.print("[yellow]Флаг --yes: подтверждение пропущено.[/yellow]")
        return

    console.print(
        "[bold red]Введите [y] для запуска тестов "
        "(данные будут затерты)[/bold red]"
    )
    console.print(
        "[green]Нажмите любую другую клавишу для отмены (данные сохранятся)[/green]"
    )
    console.print()

    answer = input("  > ").strip().lower()

    if answer != "y":
        console.print("\n[green]Отмена. Данные на дисках сохранены.[/green]")
        sys.exit(0)

    console.print()


def main() -> None:
    args = parse_args()

    console.print("[bold blue]Сканирование системы на несистемные диски...[/bold blue]")
    disks = get_non_system_disks(INTERFACE_CONFIGS)

    if not disks:
        console.print(
            "[bold red]Безопасные несистемные диски для тестов не найдены![/bold red]"
        )
        sys.exit(1)

    console.print(
        f"Обнаружено целевых дисков: [bold green]{len(disks)}[/bold green]\n"
    )

    for d in disks:
        desc = INTERFACE_DESCRIPTIONS.get(d["tran"], "")
        console.print(f"  [cyan]/dev/{d['name']}[/cyan] — {d['model']} ({d['tran']})")
        if desc:
            console.print(f"    [grey50]{desc}[/grey50]")
    console.print()

    confirm_destruction(disks, args.precond, args.yes)

    if args.precond:
        console.print(
            "[bold yellow]Прекондишнинг: "
            "запись 100% объёма каждого диска (bs=1M, --direct=1)...[/bold yellow]\n"
        )

        for disk in disks:
            console.print(
                f"  [cyan]Прекондишнинг /dev/{disk['name']}...[/cyan]"
            )
            ok = run_precondition(disk)
            if ok:
                console.print(
                    f"  [green]✓ /dev/{disk['name']} готов[/green]"
                )
            else:
                console.print(
                    f"  [red]✗ Ошибка прекондишинга /dev/{disk['name']}[/red]"
                )
        console.print()

    total_steps = sum(
        len(INTERFACE_CONFIGS[d["tran"]]) for d in disks
    )

    if args.runtime != 30:
        console.print(
            f"[grey50]Длительность теста: {args.runtime}с[/grey50]\n"
        )

    results = []

    with Live(
        build_table(results), refresh_per_second=4, console=console
    ) as live:
        progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
        )
        overall = progress.add_task(
            "[cyan]Выполнение бенчмарка...", total=total_steps
        )

        for disk in disks:
            disk_config = INTERFACE_CONFIGS[disk["tran"]]

            for t in disk_config:
                idx = len(results)
                results.append({
                    "disk": disk["name"],
                    "model": disk["model"],
                    "serial": disk["serial"],
                    "tran": disk["tran"],
                    "size": disk["size"],
                    "sector": disk["phy_sec"],
                    "test_name": f"[bold yellow]⏳ {t['name']}[/bold yellow]",
                    "iops": "...",
                    "bw": "...",
                    "lat_avg": "...",
                    "lat_p99": "...",
                })
                live.update(build_table(results))

                fio_args = list(t["args"])

                if args.runtime != 30:
                    fio_args = [
                        (
                            f"--runtime={args.runtime}"
                            if a.startswith("--runtime=")
                            else a
                        )
                        for a in fio_args
                    ]

                res = run_fio_test(disk, t["id"], fio_args)

                if "error" in res:
                    results[idx]["test_name"] = (
                        f"[red]❌ {t['name']}[/red]"
                    )
                    results[idx]["iops"] = "ERR"
                    results[idx]["bw"] = "—"
                    results[idx]["lat_avg"] = "—"
                    results[idx]["lat_p99"] = "—"
                else:
                    results[idx]["test_name"] = (
                        f"[green]✅ {t['name']}[/green]"
                    )
                    results[idx]["iops"] = f"{res['iops']:,}"
                    results[idx]["bw"] = res["bw_mb"]
                    results[idx]["lat_avg"] = res["lat_avg"]
                    results[idx]["lat_p99"] = res["lat_p99"]

                live.update(build_table(results))
                progress.advance(overall)

    console.print(
        "\n[bold green]Все тесты завершены.[/bold green]"
    )

    report_path = generate_report(disks, results, args.output)
    console.print(
        f"[bold green]Отчёт сохранён: {report_path}[/bold green]"
    )


if __name__ == "__main__":
    main()
