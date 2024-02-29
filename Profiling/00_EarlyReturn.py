from performance_fixtures import time_measurer
import asyncio


@time_measurer
async def search_fast(haystack, needle):
    for item in haystack:
        if item == needle:
            return True
    return False


@time_measurer
async def search_slow(haystack, needle):
    return_value = False

    for item in haystack:
        if item == needle:
            return_value = True
    return return_value


print("Program start...")
needle = 10000000
haystack = [i for i in range(needle)]

asyncio.run(search_slow(haystack, needle))
asyncio.run(search_fast(haystack, needle))

print("Program finished.")
