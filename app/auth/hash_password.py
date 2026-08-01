import getpass
import sys

from argon2 import PasswordHasher

MINIMUM_PASSWORD_LENGTH = 8


def main() -> None:
    password = getpass.getpass("Password: ")
    confirmation = getpass.getpass("Confirm password: ")
    if password != confirmation:
        print("Error: passwords do not match", file=sys.stderr)
        raise SystemExit(2)
    if len(password) < MINIMUM_PASSWORD_LENGTH:
        print(
            f"Error: password must contain at least {MINIMUM_PASSWORD_LENGTH} characters",
            file=sys.stderr,
        )
        raise SystemExit(2)
    print(PasswordHasher().hash(password))


if __name__ == "__main__":
    main()
