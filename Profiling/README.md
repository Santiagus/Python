# Summary for profiling python code

Examples in this folder shows some ways to optimize python code performance.

For measurement of the different code verions some decorator funcions are defined in :

- async_performance_decorators.py : For async functions
- performance_decorators.py : For sync functions

*NOTE:* Decorators use PsUtil tools. psutil is a cross-platform library for retrieving information on running processes and system utilization (CPU, memory, disks, network, sensors)

### Disabling garbage collector

The [timeit module](https://docs.python.org/3.7/library/timeit.html) temporarily disables the garbage collector.

This might impact the speed you’ll see with real-world operations if the garbage collector would normally be invoked by your operations.

Example:
```
python -m timeit -n 5 -r 1 -s "import JuliaSet" "JuliaSet.calc_pure_python(desired_width=1000, max_iterations=300)"
```

*NOTE:* Rename file avoiding numbers at the beginning.

### Simple Timing Using the Unix time Command

It displays the elapsed time during the execution of a command or script.

Install with: `sudo apt install time`

<details><summary>Example</summary>

```bash
/Profiling$ /usr/bin/time -p python 03_JuliaSet.py
Length of x: 1000
Total elements: 1000000
calculate_z_serial_purepython took 2.4911041259765625 seconds
real 2.84
user 2.59
sys 0.12
```
</details>


<details><summary>Verbose Example</summary>

```bash
/Profiling$ /usr/bin/time --verbose python 03_JuliaSet.py
Length of x: 1000
Total elements: 1000000
calculate_z_serial_purepython took 2.610788106918335 seconds
    Command being timed: "python 03_JuliaSet.py"
    User time (seconds): 2.69
    System time (seconds): 0.12
    Percent of CPU this job got: 98%
    Elapsed (wall clock) time (h:mm:ss or m:ss): 0:02.84
    Average shared text size (kbytes): 0
    Average unshared data size (kbytes): 0
    Average stack size (kbytes): 0
    Average total size (kbytes): 0
    Maximum resident set size (kbytes): 98428
    Average resident set size (kbytes): 0
    Major (requiring I/O) page faults: 0
    Minor (reclaiming a frame) page faults: 21800
    Voluntary context switches: 355
    Involuntary context switches: 8
    Swaps: 0
    File system inputs: 0
    File system outputs: 0
    Socket messages sent: 0
    Socket messages received: 0
    Signals delivered: 0
    Page size (bytes): 4096
    Exit status: 0
```
</details>


### CProfiling Module

CMD: `$ python -m cProfile -s cumulative 03_JuliaSet.py`

<details><summary>Example</summary>

```bash

Length of x: 1000
Total elements: 1000000
calculate_z_serial_purepython took 7.626293420791626 seconds
         36221995 function calls in 8.172 seconds

   Ordered by: cumulative time

   ncalls  tottime  percall  cumtime  percall filename:lineno(function)
        1    0.000    0.000    8.172    8.172 {built-in method builtins.exec}
        1    0.047    0.047    8.172    8.172 03_JuliaSet.py:1(<module>)
        1    0.397    0.397    8.125    8.125 03_JuliaSet.py:30(calc_pure_python)
        1    5.567    5.567    7.626    7.626 03_JuliaSet.py:16(calculate_z_serial_purepython)
 34219980    2.059    0.000    2.059    0.000 {built-in method builtins.abs}
  2002000    0.098    0.000    0.098    0.000 {method 'append' of 'list' objects}
        1    0.003    0.003    0.003    0.003 {built-in method builtins.sum}
        3    0.000    0.000    0.000    0.000 {built-in method builtins.print}
        4    0.000    0.000    0.000    0.000 {built-in method builtins.len}
        2    0.000    0.000    0.000    0.000 {built-in method time.time}
        1    0.000    0.000    0.000    0.000 {method 'disable' of '_lsprof.Profiler' objects}

```
</details>


### Python cProfile load


This Python script will give the same info showed in the previous report:

<details><summary>04_JuliaSetStats.py</summary>

```python
import pstats

p = pstats.Stats("profile.stats")
p.sort_stats("cumulative")
p.print_stats("cumulative")
p.print_callers()
```
</details>


### Visualizing cProfile Output with SnakeViz

[Snakeviz](https://jiffyclub.github.io/snakeviz/) is a visualizer that draws the output of cProfile

`python -m pip install --upgrade pip setuptools wheel`
`pip install snakeviz`

1. Generate profile.stats
`python -m cProfile -o profile.stats 03_JuliaSet.py`
2. Run snakeviz
`snakeviz profile.stats -s`

### line_profiler for Line-by-Line Measurements
1. Install line profiler : \
`pip install line_profiler`

2. Use ***@profile*** decorator to mark the chosen function
    ```python
    @profile
    def calc_pure_python(desired_width, max_iterations):
    ...
    ```
3. Execute the profiler: \
    `kernprof -l -v 03_JuliaSet.py`


<details><summary> Output </summary>

```bash
kernprof -l -v 03_JuliaSet.py
Length of x: 1000
Total elements: 1000000
calculate_z_serial_purepython took 8.200989961624146 seconds
Wrote profile results to 03_JuliaSet.py.lprof
Timer unit: 1e-06 s

Total time: 8.74415 s
File: 03_JuliaSet.py
Function: calc_pure_python at line 30

Line #      Hits         Time  Per Hit   % Time  Line Contents
==============================================================
    30                                           @profile
    31                                           def calc_pure_python(desired_width, max_iterations):
    32                                               """Create a list of complex coordinates (zs) and complex parameters (cs),
    33                                               build Julia set"""
    34         1          1.7      1.7      0.0      x_step = (x2 - x1) / desired_width
    35         1          0.3      0.3      0.0      y_step = (y1 - y2) / desired_width
    36         1          0.2      0.2      0.0      x = []
    37         1          0.1      0.1      0.0      y = []
    38         1          0.1      0.1      0.0      ycoord = y2
    39      1001        100.4      0.1      0.0      while ycoord > y1:
    40      1000        141.4      0.1      0.0          y.append(ycoord)
    41      1000         97.5      0.1      0.0          ycoord += y_step
    42         1          0.1      0.1      0.0      xcoord = x1
    43      1001        101.5      0.1      0.0      while xcoord < x2:
    44      1000        124.7      0.1      0.0          x.append(xcoord)
    45      1000        105.4      0.1      0.0          xcoord += x_step
    46                                               # build a list of coordinates and the initial condition for each cell.
    47                                               # Note that our initial condition is a constant and could easily be removed,
    48                                               # we use it to simulate a real-world scenario with several inputs to our
    49                                               # function
    50         1          0.1      0.1      0.0      zs = []
    51         1          0.1      0.1      0.0      cs = []
    52      1001        133.0      0.1      0.0      for ycoord in y:
    53   1001000      94495.5      0.1      1.1          for xcoord in x:
    54   1000000     215159.6      0.2      2.5              zs.append(complex(xcoord, ycoord))
    55   1000000     229558.1      0.2      2.6              cs.append(complex(c_real, c_imag))
    56         1         54.6     54.6      0.0      print("Length of x:", len(x))
    57         1          4.5      4.5      0.0      print("Total elements:", len(zs))
    58         1          2.6      2.6      0.0      start_time = time.time()
    59         1    8200978.3    8e+06     93.8      output = calculate_z_serial_purepython(max_iterations, zs, cs)
    60         1          2.5      2.5      0.0      end_time = time.time()
    61         1          0.9      0.9      0.0      secs = end_time - start_time
    62         1         49.1     49.1      0.0      print(calculate_z_serial_purepython.__name__ + " took", secs, "seconds")
    63                                               # This sum is expected for a 1000^2 grid with 300 iterations
    64                                               # It ensures that our code evolves exactly as we'd intended
    65         1       3033.4   3033.4      0.0      assert sum(output) == 33219980
```
</details>


## Using memory_profiler to Diagnose Memory Usage

1. Install line profiler :
`$ pip install memory_profiler`
2. Use ***@profile*** decorator to mark the chosen function
    ```python
    @profile
    def calc_pure_python(desired_width, max_iterations):
    ...
    ```
3. Execute the profiler:
`python -m memory_profiler 03_JuliaSet.py`

<details><summary> Output </summary>

```bash
Length of x: 1000
Total elements: 1000000
calculate_z_serial_purepython took 22.655635118484497 seconds
Filename: 03_JuliaSet.py

Line #    Mem usage    Increment  Occurrences   Line Contents
=============================================================
    30   21.883 MiB   21.883 MiB           1   @profile
    31                                         def calc_pure_python(desired_width, max_iterations):
    32                                             """Create a list of complex coordinates (zs) and complex parameters (cs),
    33                                             build Julia set"""
    34   21.883 MiB    0.000 MiB           1       x_step = (x2 - x1) / desired_width
    35   21.883 MiB    0.000 MiB           1       y_step = (y1 - y2) / desired_width
    36   21.883 MiB    0.000 MiB           1       x = []
    37   21.883 MiB    0.000 MiB           1       y = []
    38   21.883 MiB    0.000 MiB           1       ycoord = y2
    39   21.883 MiB    0.000 MiB        1001       while ycoord > y1:
    40   21.883 MiB    0.000 MiB        1000           y.append(ycoord)
    41   21.883 MiB    0.000 MiB        1000           ycoord += y_step
    42   21.883 MiB    0.000 MiB           1       xcoord = x1
    43   21.883 MiB    0.000 MiB        1001       while xcoord < x2:
    44   21.883 MiB    0.000 MiB        1000           x.append(xcoord)
    45   21.883 MiB    0.000 MiB        1000           xcoord += x_step
    46                                             # build a list of coordinates and the initial condition for each cell.
    47                                             # Note that our initial condition is a constant and could easily be removed,
    48                                             # we use it to simulate a real-world scenario with several inputs to our
    49                                             # function
    50   21.883 MiB    0.000 MiB           1       zs = []
    51   21.883 MiB    0.000 MiB           1       cs = []
    52   98.711 MiB    0.000 MiB        1001       for ycoord in y:
    53   98.711 MiB   45.090 MiB     1001000           for xcoord in x:
    54   98.711 MiB    9.191 MiB     1000000               zs.append(complex(xcoord, ycoord))
    55   98.711 MiB   22.547 MiB     1000000               cs.append(complex(c_real, c_imag))
    56   98.711 MiB    0.000 MiB           1       print("Length of x:", len(x))
    57   98.711 MiB    0.000 MiB           1       print("Total elements:", len(zs))
    58   98.711 MiB    0.000 MiB           1       start_time = time.time()
    59  109.484 MiB   10.773 MiB           1       output = calculate_z_serial_purepython(max_iterations, zs, cs)
    60  109.484 MiB    0.000 MiB           1       end_time = time.time()
    61  109.484 MiB    0.000 MiB           1       secs = end_time - start_time
    62  109.484 MiB    0.000 MiB           1       print(calculate_z_serial_purepython.__name__ + " took", secs, "seconds")
    63                                             # This sum is expected for a 1000^2 grid with 300 iterations
    64                                             # It ensures that our code evolves exactly as we'd intended
    65  109.484 MiB    0.000 MiB           1       assert sum(output) == 33219980
```
</details>

### Sample memory use over time and plot it
1. Sample memory use with: \
`$ mprof run 03_JuliaSet.py`

    ```bash
    mprof: Sampling memory every 0.1s
    running new process
    running as a Python program...
    Length of x: 1000
    Total elements: 1000000
    calculate_z_serial_purepython took 2.638066053390503 seconds
    ```
2. Plot the results

    ```bash
    $ pip install matplotlib # Install dependency packages
    $ mprof plot             # Run
    ```

Plot shows the memory using brackets to shows where in time the profiled functions are entered.


### Introspecting an Existing Process with PySpy

***py-spy*** is an sampling profiler than introspects an already-running Python process and reports in the console with a top-like display.

1. Install :\
`pip install py-spy`
2. Sample recording: \
`py-spy record python 03_JuliaSet.py`
3. Run (specifying an output file): \
`py-spy record -o profile.svg -- python 03_JuliaSet.py`
4. Open the generated .svg file with a web browser

### Using the dis Module to Examine CPython Bytecode
The ***dis*** module lets us inspect the underlying bytecode that we run inside the stackbased CPython virtual machine.

Run a python terminal and proceed to disassembly some functions:

Run : `$ python`

<details><summary>search_slow</summary>

```python
>>> import dis
>>> import EarlyReturn
>>> dis.dis(EarlyReturn.search_slow)
  8           0 RESUME                   0

  9           2 LOAD_CONST               1 (False)
              4 STORE_FAST               2 (return_value)

 11           6 LOAD_FAST                0 (haystack)
              8 GET_ITER
        >>   10 FOR_ITER                10 (to 32)
             12 STORE_FAST               3 (item)

 12          14 LOAD_FAST                3 (item)
             16 LOAD_FAST                1 (needle)
             18 COMPARE_OP               2 (==)
             24 POP_JUMP_FORWARD_IF_FALSE     2 (to 30)

 13          26 LOAD_CONST               2 (True)
             28 STORE_FAST               2 (return_value)
        >>   30 JUMP_BACKWARD           11 (to 10)

 14     >>   32 LOAD_FAST                2 (return_value)
             34 RETURN_VALUE
```
</details>

<details><summary>search_fast</summary>

```python
>>> dis.dis(EarlyReturn.search_fast)
  1           0 RESUME                   0

  2           2 LOAD_FAST                0 (haystack)
              4 GET_ITER
        >>    6 FOR_ITER                11 (to 30)
              8 STORE_FAST               2 (item)

  3          10 LOAD_FAST                2 (item)
             12 LOAD_FAST                1 (needle)
             14 COMPARE_OP               2 (==)
             20 POP_JUMP_FORWARD_IF_FALSE     3 (to 28)

  4          22 POP_TOP
             24 LOAD_CONST               1 (True)
             26 RETURN_VALUE

  3     >>   28 JUMP_BACKWARD           12 (to 6)

  5     >>   30 LOAD_CONST               2 (False)
             32 RETURN_VALUE
```
</details>


### Built in function VS Loop

This is an example that sum up values in a range with two different approaches:
- A loop that accumulate values in a variable
- Use of the sum build-in function

<details><summary>02_BuiltSUmVSLoop.py</summary>

```python
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
```
</details>

</br>

*NOTE:* As a rule of thumb the more lines in source code the more bytecode generated that will lead to more overhead.

<details><summary>iPython output </summary>

```bash
In [10]: %timeit fn_terse()
8.34 ms ± 383 µs per loop (mean ± std. dev. of 7 runs, 100 loops each)

In [11]: %timeit fn_expressive()
20.1 ms ± 578 µs per loop (mean ± std. dev. of 7 runs, 10 loops each)
```
</details>

### ByteCode Comparison

`$ ipython`

<details><summary>fn_expressive</summary>

```python
In [2]: import dis
In [3]: from BuiltSumVSloop import fn_expressive, fn_terse
In [4]: dis.dis(fn_expressive)
  1           0 RESUME                   0
  2           2 LOAD_CONST               1 (0)
              4 STORE_FAST               1 (total)
  3           6 LOAD_GLOBAL              1 (NULL + range)
             18 LOAD_FAST                0 (upper)
             20 PRECALL                  1
             24 CALL                     1
             34 GET_ITER
        >>   36 FOR_ITER                 7 (to 52)
             38 STORE_FAST               2 (n)
  4          40 LOAD_FAST                1 (total)
             42 LOAD_FAST                2 (n)
             44 BINARY_OP               13 (+=)
             48 STORE_FAST               1 (total)
             50 JUMP_BACKWARD            8 (to 36)
  5     >>   52 LOAD_FAST                1 (total)
             54 RETURN_VALUE
```
</details>


<details><summary>fn_terse</summary>

```python
In [5]: dis.dis(fn_terse)
  8           0 RESUME                   0
  9           2 LOAD_GLOBAL              1 (NULL + sum)
             14 LOAD_GLOBAL              3 (NULL + range)
             26 LOAD_FAST                0 (upper)
             28 PRECALL                  1
             32 CALL                     1
             42 PRECALL                  1
             46 CALL                     1
             56 RETURN_VALUE
```
</details>


## Unit test example

***NOTE:*** @profile decorator requires to use some profiler like memory_profiler or kernprof, running the code with pytest or python without the proper module will lead to an error because the decorator is not into the local namespace.

no-op decorator will made posible to run the test/code without modifying the code.

<details><summary>05_UnitTestSample.py</summary>

```python
import time

def test_some_fn():
    """Check basic behaviors for our function"""
    assert some_fn(2) == 4
    assert some_fn(1) == 1
    assert some_fn(-1) == 1

@profile
def some_fn(useful_input):
    """An expensive function that we wish to both test and profile"""
    # artificial "we're doing something clever and expensive" delay
    time.sleep(1)
    return useful_input**2

if __name__ == "__main__":
    print(f"Example call `some_fn(2)` == {some_fn(2)}")
```
</details>
</br>

Add the no-op decorator ath the start of the code.

<details><summary>no-op decorator</summary>

```python
# check for line_profiler or memory_profiler in the local scope, both
# are injected by their respective tools or they're absent
# if these tools aren't being used (in which case we need to substitute
# a dummy @profile decorator)
if "line_profiler" not in dir() and "profile" not in dir():
    def profile(func):
        return func
```
</details>

## Check

```bash
$ pytest 05_UnitTestSample.py
$ kernprof -l -v 05_UnitTestSample.py
$ python -m memory_profiler 05_UnitTestSample.py
```


## Strategies to Profile Your Code Successfully

Results obtained for different versions of the code should be comparable when those were run in same conditions.

Than means same HW and system configuration, most actual platforms have a performance/turbo mode that modify CPU/RAM frequency temporarily. Than will affect to the results.

Some condiderations to create a more stable benchmark:
- Set a constant CPU/RAM frequency in BIOS
- Run test always in the same power mode.
- Disable background tools.
- Run test multiple times and discard abnormal measurements.
- In Unix system drop to run level 1 so that no other tasks are runnig.

