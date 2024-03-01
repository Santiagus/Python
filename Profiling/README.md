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


