"""The built-in exercise library: data from the exercises dataset, media downloaded at runtime.

`exercises.json` next to this file is built by `scripts/build_library.py` from the dataset at `DATASET_COMMIT`.
"""

# The pinned commit of https://github.com/hasaneyldrm/exercises-dataset. The build script reads it from this file.
DATASET_COMMIT = "7455efae41b330c265e7cd4b78dfa848e7ce5ebd"

# The same for every library exercise, so it is stored once and returned with each one.
ATTRIBUTION = "© Gym visual — https://gymvisual.com/"
