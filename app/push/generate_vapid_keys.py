import base64

from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid01  # type: ignore[import-untyped]


def encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def main() -> None:
    vapid = Vapid01()
    vapid.generate_keys()
    private_value = vapid.private_key.private_numbers().private_value.to_bytes(32, "big")
    public_value = vapid.public_key.public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    print(f"VAPID_PUBLIC_KEY={encode(public_value)}")
    print(f"VAPID_PRIVATE_KEY={encode(private_value)}")


if __name__ == "__main__":
    main()
