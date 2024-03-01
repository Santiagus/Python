from async_performance_decortors import time_measurer, memory_usage
import asyncio


@time_measurer
@memory_usage
async def search_unknown_tuple(haystack, needle):
    return any((item == needle for item in haystack))


@time_measurer
@memory_usage
async def search_unknown_list(haystack, needle):
    return any([item == needle for item in haystack])


print("Program start...")
needle = 1000000
haystack = (i for i in range(needle * 2))

asyncio.run(search_unknown_tuple(haystack, needle))
asyncio.run(search_unknown_list(haystack, needle))

print("Program finished.")
