"""
FIO-конфиги для SAS накопителей.

SAS — серверный интерфейс с хорошей поддержкой очередей.
Случайный доступ тестируется в 2 потока (QD32 x 2 = QD64).
Последовательные тесты используют bs=64k.
"""

TESTS = [
    {
        "id": "seq_read",
        "name": "1. Послед. Чтение",
        "args": ["--rw=read", "--bs=64k", "--iodepth=32", "--numjobs=1",
                 "--runtime=30", "--time_based"],
    },
    {
        "id": "seq_write",
        "name": "2. Послед. Запись",
        "args": ["--rw=write", "--bs=64k", "--iodepth=32", "--numjobs=1",
                 "--runtime=30", "--time_based"],
    },
    {
        "id": "rand_read",
        "name": "3. Случ. Чтение 4k",
        "args": ["--rw=randread", "--bs=4k", "--iodepth=32", "--numjobs=2",
                 "--runtime=30", "--time_based"],
    },
    {
        "id": "rand_write",
        "name": "4. Случ. Запись 4k",
        "args": ["--rw=randwrite", "--bs=4k", "--iodepth=32", "--numjobs=2",
                 "--runtime=30", "--time_based"],
    },
]

DESCRIPTION = (
    "SAS — серверный интерфейс. "
    "Случайный доступ: 2 потока (QD64) — сбалансированный профиль. "
    "Последовательный: bs=64k."
)
