import sys
import json
import subprocess
from rich.console import Console
from rich.table import Table
from rich.live import Live
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

console = Console()

# Базовые матрицы конфигураций для разных интерфейсов (без прекондишена)
# Параметры bs будут автоматически скорректированы функцией run_fio_test, если сектор равен 4096
INTERFACE_CONFIGS = {
    "NVME": [
        {"id": "seq_read",  "name": "1. Послед. Чтение", "args": ["--rw=read",      "--bs=128k", "--iodepth=32", "--numjobs=1", "--runtime=30", "--time_based"]},
        {"id": "seq_write", "name": "2. Послед. Запись", "args": ["--rw=write",     "--bs=128k", "--iodepth=32", "--numjobs=1", "--runtime=30", "--time_based"]},
        {"id": "rand_read", "name": "3. Случ. Чтение 4k", "args": ["--rw=randread",  "--bs=4k",   "--iodepth=32", "--numjobs=8", "--runtime=30", "--time_based"]},
        {"id": "rand_write","name": "4. Случ. Запись 4k", "args": ["--rw=randwrite", "--bs=4k",   "--iodepth=32", "--numjobs=8", "--runtime=30", "--time_based"]}
    ],
    "SAS": [
        {"id": "seq_read",  "name": "1. Послед. Чтение", "args": ["--rw=read",      "--bs=64k",  "--iodepth=32", "--numjobs=1", "--runtime=30", "--time_based"]},
        {"id": "seq_write", "name": "2. Послед. Запись", "args": ["--rw=write",     "--bs=64k",  "--iodepth=32", "--numjobs=1", "--runtime=30", "--time_based"]},
        {"id": "rand_read", "name": "3. Случ. Чтение 4k", "args": ["--rw=randread",  "--bs=4k",   "--iodepth=32", "--numjobs=2", "--runtime=30", "--time_based"]},
        {"id": "rand_write","name": "4. Случ. Запись 4k", "args": ["--rw=randwrite", "--bs=4k",   "--iodepth=32", "--numjobs=2", "--runtime=30", "--time_based"]}
    ],
    "SATA": [
        {"id": "seq_read",  "name": "1. Послед. Чтение", "args": ["--rw=read",      "--bs=64k",  "--iodepth=32", "--numjobs=1", "--runtime=30", "--time_based"]},
        {"id": "seq_write", "name": "2. Послед. Запись", "args": ["--rw=write",     "--bs=64k",  "--iodepth=32", "--numjobs=1", "--runtime=30", "--time_based"]},
        {"id": "rand_read", "name": "3. Случ. Чтение 4k", "args": ["--rw=randread",  "--bs=4k",   "--iodepth=32", "--numjobs=1", "--runtime=30", "--time_based"]},
        {"id": "rand_write","name": "4. Случ. Запись 4k", "args": ["--rw=randwrite", "--bs=4k",   "--iodepth=32", "--numjobs=1", "--runtime=30", "--time_based"]}
    ]
}

def get_non_system_disks():
    """Безопасно сканирует систему и отфильтровывает системные накопители."""
    cmd = ["lsblk", "--json", "-o", "NAME,TYPE,SIZE,MODEL,SERIAL,TRAN,MOUNTPOINT,PHY-SEC"]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    data = json.loads(res.stdout).get("blockdevices", [])
    
    target_disks = []
    for d in data:
        if d.get("type") == "disk" and d.get("size") not in ("0B", "0"):
            # Проверка корня системы на диске или его разделах
            has_root = d.get("mountpoint") == "/"
            if "children" in d:
                for child in d["children"]:
                    if child.get("mountpoint") == "/":
                        has_root = True
            
            if not has_root:
                tran = d.get("tran")
                if not tran:
                    tran = "NVME" if "nvme" in d["name"] else "SATA"
                
                tran = tran.upper()
                if tran not in INTERFACE_CONFIGS:
                    tran = "SATA"

                target_disks.append({
                    "name": d["name"],
                    "path": f"/dev/{d['name']}",
                    "model": d.get("model") or "Unknown Model",
                    "serial": d.get("serial") or "Unknown SN",
                    "tran": tran,
                    "size": d.get("size"),
                    "phy_sec": int(d.get("phy-sec") or 512)
                })
    return target_disks

def run_fio_test(disk_info, test_id, base_args):
    """Запускает FIO с автоподстройкой под физический размер сектора диска."""
    disk_path = disk_info["path"]
    sector_size = disk_info["phy_sec"]
    
    # Клонируем аргументы, чтобы избежать порчи глобального конфига
    fio_args = base_args.copy()
    
    # ДИНАМИЧЕСКАЯ АВТОПОДСТРОКА ПОД СЕКТОР 4Kn
    if sector_size == 4096:
        if "rand" in test_id:
            # Защита: гарантируем, что размер блока случайного теста не упадет ниже физического сектора (4k)
            fio_args = [a if not a.startswith("--bs=") else "--bs=4k" for a in fio_args]
        elif "seq" in test_id:
            # Оптимизация: для последовательных тестов на 4Kn дисках выставляем эффективные 128k
            fio_args = [a if not a.startswith("--bs=") else "--bs=128k" for a in fio_args]

    # Сборка финальной JSON команды
    cmd = [
        "fio", f"--name={test_id}", f"--filename={disk_path}",
        "--direct=1", "--ioengine=libaio", "--group_reporting",
        "--norandommap", "--output-format=json"
    ] + fio_args
    
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        return {"error": "FIO Error"}
        
    try:
        fio_data = json.loads(res.stdout)
        job = fio_data["jobs"][0]
        
        mode = "read" if "read" in test_id else "write"
        stats = job[mode]
        
        # Конвертация наносекунд в миллисекунды (ms)
        avg_lat = stats["lat_ns"]["mean"] / 1_000_000
        p99_lat = stats["clat_ns"]["percentile"]["99.000000"] / 1_000_000
        
        return {
            "iops": int(stats["iops"]),
            "bw_mb": round(stats["bw"] / 1024, 2),
            "lat_avg": round(avg_lat, 2),
            "lat_p99": round(p99_lat, 2)
        }
    except Exception:
        return {"error": "Parse Error"}

def generate_table(results):
    """Строит структуру таблицы Rich."""
    table = Table(title="[bold green]Результаты автоматического тестирования накопителей (FIO)[/bold green]", show_lines=True)
    table.add_column("Диск", style="cyan")
    table.add_column("Модель / Серийник", style="magenta")
    table.add_column("Интерфейс / Объем")
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
            str(r["lat_p99"])
        )
    return table

def main():
    console.print("[bold blue]Сканирование серверной системы на несистемные диски...[/bold blue]")
    disks = get_non_system_disks()
    
    if not disks:
        console.print("[bold red]Критическая ошибка: Безопасные несистемные диски для тестов не найдены![/bold red]")
        sys.exit(1)
        
    console.print(f"Обнаружено целевых дисков: [bold green]{len(disks)}[/bold green]\n")
    final_results = []
    total_steps = sum(len(INTERFACE_CONFIGS[d["tran"]]) for d in disks)
    
    with Live(generate_table(final_results), refresh_per_second=4) as live:
        progress = Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), BarColumn(), TaskProgressColumn())
        overall_task = progress.add_task("[cyan]Выполнение бенчмарка...", total=total_steps)
        
        for disk in disks:
            disk_config = INTERFACE_CONFIGS[disk["tran"]]
            for t in disk_config:
                current_row_idx = len(final_results)
                final_results.append({
                    "disk": disk["name"], "model": disk["model"], "serial": disk["serial"], "tran": disk["tran"], "size": disk["size"], "sector": disk["phy_sec"],
                    "test_name": f"[bold yellow]⏳ {t['name']}[/bold yellow]", "iops": "...", "bw": "...", "lat_avg": "...", "lat_p99": "..."
                })
                live.update(generate_table(final_results))
                
                # Запуск изолированного подтеста
                res = run_fio_test(disk, t["id"], t["args"])
                
                if "error" in res:
                    final_results[current_row_idx]["test_name"] = f"[red]❌ {t['name']}[/red]"
                else:
                    final_results[current_row_idx]["test_name"] = f"[green]✅ {t['name']}[/green]"
                    final_results[current_row_idx]["iops"] = f"{res['iops']:,}"
                    final_results[current_row_idx]["bw"] = res["bw_mb"]
                    final_results[current_row_idx]["lat_avg"] = res["lat_avg"]
                    final_results[current_row_idx]["lat_p99"] = res["lat_p99"]
                
                live.update(generate_table(final_results))
                progress.advance(overall_task)
                
    console.print("\n[bold green]🎉 Все автоматические тесты завершены. Данные зафиксированы успешно![/bold green]")

if __name__ == "__main__":
    main()
