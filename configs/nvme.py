"""
FIO-конфиги для NVMe накопителей.

NVMe раскрывает себя на большой глубине очереди.
Случайный доступ тестируется в 8 параллельных потоков (QD32 x 8 = QD256).
Последовательные тесты используют bs=128k для максимальной пропускной способности шины.
"""

TESTS = [
    {
        "id": "seq_read",
        "name": "1. Послед. Чтение",
        "args": ["--rw=read", "--bs=128k", "--iodepth=32", "--numjobs=1",
                 "--runtime=30", "--time_based"],
    },
    {
        "id": "seq_write",
        "name": "2. Послед. Запись",
        "args": ["--rw=write", "--bs=128k", "--iodepth=32", "--numjobs=1",
                 "--runtime=30", "--time_based"],
    },
    {
        "id": "rand_read",
        "name": "3. Случ. Чтение 4k",
        "args": ["--rw=randread", "--bs=4k", "--iodepth=32", "--numjobs=8",
                 "--runtime=30", "--time_based"],
    },
    {
        "id": "rand_write",
        "name": "4. Случ. Запись 4k",
        "args": ["--rw=randwrite", "--bs=4k", "--iodepth=32", "--numjobs=8",
                 "--runtime=30", "--time_based"],
    },
]

DESCRIPTION = (
    "NVMe — высокопроизводительный интерфейс. "
    "Случайный доступ: 8 потоков (QD256) для выжимания максимума из контроллера. "
    "Последовательный: bs=128k для飽和 шины PCIe."
)
