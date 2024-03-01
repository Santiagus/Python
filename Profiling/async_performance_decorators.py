import time
import psutil
from functools import wraps


def time_measurer(func):
    """
    A decorator that measures the execution time of an asynchronous function.

    Parameters:
    - `func` (callable): The function to be measured.

    Returns:
    - callable: The decorated function.
    """

    @wraps(func)
    async def wrapper(*args, **kwargs):
        start_time = time.time()
        result = await func(*args, **kwargs)
        end_time = time.time()
        execution_time = end_time - start_time
        print(f"Execution time of {func.__name__}: {execution_time:.4f} seconds")
        return result

    return wrapper


def cpu_usage(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        """
        A decorator that measures the CPU usage of an asynchronous function.

        Parameters:
        - `func` (callable): The function to be measured.

        Returns:
        - callable: The decorated function.
        """
        process = psutil.Process()
        start_cpu_usage = process.cpu_percent(interval=None)
        result = await func(*args, **kwargs)
        end_cpu_usage = process.cpu_percent(interval=None)
        cpu_usage_diff = end_cpu_usage - start_cpu_usage
        print(f"CPU usage of {func.__name__}: {cpu_usage_diff}%")
        return result

    return wrapper


def format_size(size_bytes):
    """
    Convert a size in bytes to a human-readable format.

    Parameters:
    - `size_bytes` (int): The size in bytes.

    Returns:
    - str: The human-readable size.
    """
    suffixes = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    size = float(size_bytes)
    while size >= 1024 and i < len(suffixes) - 1:
        size /= 1024
        i += 1
    return f"{size:.2f} {suffixes[i]}"


def memory_usage(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        """
        A decorator that measures the memory usage of an asynchronous function.

        Parameters:
        - `func` (callable): The function to be measured.

        Returns:
        - callable: The decorated function.
        """
        process = psutil.Process()
        start_memory_usage = process.memory_info().rss
        result = await func(*args, **kwargs)
        end_memory_usage = process.memory_info().rss
        memory_usage_diff = end_memory_usage - start_memory_usage
        formatted_memory_usage = format_size(memory_usage_diff)
        print(f"Memory usage of {func.__name__}: {formatted_memory_usage}")
        return result

    return wrapper
