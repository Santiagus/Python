# Agent Guidelines & Local Invariants

* **Creation Mask (`umask 022`)**: Always execute commands creating files or directories with `umask 022` (directories `755`, regular files `644`). Never generate `777` or `666` permissions.
