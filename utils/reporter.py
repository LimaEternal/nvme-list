"""
Генерация MD-отчёта с результатами тестирования.

Создаёт Markdown-файл с таблицами, удобный для чтения и публикации.
"""

from datetime import datetime
from pathlib import Path


def generate_report(
    disks: list[dict],
    results: list[dict],
    output_path: str | Path | None = None,
) -> Path:
    """
    Генерирует MD-файл с таблицей результатов.

    Параметры:
        disks       — список словарей с данными дисков
        results     — список словарей с результатами тестов
        output_path — путь для выходного файла (по умолчанию fio_report_<timestamp>.md)

    Возвращает:
        Path к созданному файлу
    """
    if output_path is None:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        output_path = Path(f"fio_report_{timestamp}.md")
    else:
        output_path = Path(output_path)

    lines = []

    lines.append("# Отчёт тестирования накопителей (FIO)")
    lines.append("")
    lines.append(f"> Дата: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")

    lines.append("## Обнаруженные диски")
    lines.append("")
    lines.append("| Диск | Модель | Серийный номер | Интерфейс | Объём | Физ. сектор |")
    lines.append("|------|--------|----------------|-----------|-------|-------------|")

    for d in disks:
        lines.append(
            f"| /dev/{d['name']} | {d['model']} | {d['serial']} "
            f"| {d['tran']} | {d['size']} | {d['phy_sec']}B |"
        )

    lines.append("")
    lines.append("## Результаты тестирования")
    lines.append("")

    current_disk = None

    for r in results:
        disk_key = r["disk"]

        if disk_key != current_disk:
            current_disk = disk_key
            lines.append(f"### /dev/{disk_key} ({r['model']})")
            lines.append("")
            lines.append(
                "| Тест | IOPS | Скорость (МБ/с) | Lat Avg (мс) | Lat p99 (мс) |"
            )
            lines.append(
                "|------|------|-----------------|--------------|--------------|"
            )

        status = "OK" if not r.get("error") else "ERROR"

        if r.get("error"):
            lines.append(
                f"| {r['test_name']} | {status} | — | — | — |"
            )
        else:
            lines.append(
                f"| {r['test_name']} | {r['iops']} | {r['bw']} "
                f"| {r['lat_avg']} | {r['lat_p99']} |"
            )

    lines.append("")
    lines.append("---")
    lines.append(f"*Отчёт сгенерирован автоматически*")

    output_path.write_text("\n".join(lines), encoding="utf-8")

    return output_path
