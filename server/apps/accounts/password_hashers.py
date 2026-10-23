"""Tuned Argon2id password hasher.

Django's ``Argon2PasswordHasher`` ships with weak defaults (512 KiB memory,
well below the OWASP floor of ~19 MiB). The parameters below cost roughly
50–150 ms per login while making every *offline* guess against a leaked
hash equally expensive.

Parameters are encoded in each hash string, so existing hashes (if any)
stay valid and are upgraded on the next password change.
"""

from django.contrib.auth.hashers import Argon2PasswordHasher


class TunedArgon2PasswordHasher(Argon2PasswordHasher):
    time_cost = 3
    memory_cost = 65536  # KiB → 64 MiB (OWASP minimum: 19 MiB)
    parallelism = 4
