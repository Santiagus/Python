from performance_decorators import time_measurer


@time_measurer
def fn_expressive(upper=1_000_000):
    total = 0
    for n in range(upper):
        total += n
    return total


@time_measurer
def fn_terse(upper=1_000_000):
    return sum(range(upper))


if __name__ == "__main__":
    fn_expressive()
    fn_terse()
