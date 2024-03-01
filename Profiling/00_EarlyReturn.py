from performance_decorators import time_measurer, memory_usage, cpu_usage


@time_measurer
@memory_usage
@cpu_usage
def search_fast(haystack, needle):
    for item in haystack:
        if item == needle:
            return True
    return False


@time_measurer
@memory_usage
@cpu_usage
def search_slow(haystack, needle):
    return_value = False

    for item in haystack:
        if item == needle:
            return_value = True
    return return_value


print("Program start...")
needle = 10000000
haystack = [i for i in range(needle)]

search_slow(haystack, needle)
search_fast(haystack, needle)

print("Program finished.")
