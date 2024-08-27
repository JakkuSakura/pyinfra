import re

units = {"B": 1, "KB": 10 ** 3, "MB": 10 ** 6, "GB": 10 ** 9, "TB": 10 ** 12,
         "KIB": 2 ** 10, "MIB": 2 ** 20, "GIB": 2 ** 30, "TIB": 2 ** 40}


def parse_human_readable_size(size: str) -> int:
    size = size.upper()
    # print("parsing size ", size)
    if not re.match(r' ', size):
        size = re.sub(r'([KMGT]?I?[B])', r' \1', size)
    number, unit = [string.strip() for string in size.split()]
    return int(float(number) * units[unit])

def parse_size(size: str | int) -> int:
    if isinstance(size, int):
        return size
    return parse_human_readable_size(size)
def test_parse_human_readable_size():
    example_strings = [
        "1024b", "10.43 KB", "11 GB", "343.1 MB",
        "10.43KB", "11GB", "343.1MB", "10.43 kb",
        "11 gb", "343.1 mb", "10.43kb", "11gb",
        "343.1mb", "1024Kib", "10.43 KiB", "11 GiB",
        "343.1 MiB", "10.43KiB", "11GiB", "343.1MiB",
        "10.43 kib", "11 gib"
    ]
    for example_string in example_strings:
        print(example_string, parse_human_readable_size(example_string))
