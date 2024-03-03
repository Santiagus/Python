# Summary for profiling python code

Examples in this folder shows some ways to optimize python code performance.

For measurement of the different code verions some decorator funcions are defined in :

- async_performance_decorators.py : For async functions
- performance_decorators.py : For sync functions

*NOTE:* Decorators use PsUtil tools. psutil is a cross-platform library for retrieving information on running processes and system utilization (CPU, memory, disks, network, sensors)

### Disabling garbage collector

The [timeit module](https://docs.python.org/3.7/library/timeit.html) temporarily disables the garbage collector.

This might impact the speed you’ll see with real-world operations
if the garbage collector would normally be invoked by your operations.

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
1. Install line profiler : `pip install line_profiler`

2. Use ***@profile*** decorator to mark the chosen function

3. Execute the profler: `kernprof -l -v 03_JuliaSet.py`


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


