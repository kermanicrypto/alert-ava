import re
import base58


# EVM:
# 0x + exactly 40 hexadecimal characters
EVM_PATTERN = re.compile(
    r"(?<![A-Fa-f0-9])0x[A-Fa-f0-9]{40}(?![A-Fa-f0-9])"
)


# Solana Base58 public keys are usually 32-44 chars when encoded.
SOLANA_PATTERN = re.compile(
    r"(?<![1-9A-HJ-NP-Za-km-z])"
    r"[1-9A-HJ-NP-Za-km-z]{32,44}"
    r"(?![1-9A-HJ-NP-Za-km-z])"
)


def is_valid_solana_address(value: str) -> bool:
    """
    A Solana public key/mint must decode
    to exactly 32 bytes.
    """
    try:
        decoded = base58.b58decode(value)
        return len(decoded) == 32
    except Exception:
        return False


def find_contracts(content: str):
    """
    Returns contracts found in the content.

    Example:
    [
        {
            "chain": "evm",
            "address": "0x..."
        },
        {
            "chain": "solana",
            "address": "..."
        }
    ]
    """

    if not content:
        return []

    contracts = []
    seen = set()

    # -------------------------
    # EVM
    # -------------------------

    evm_matches = list(EVM_PATTERN.finditer(content))

    evm_ranges = [
        (match.start(), match.end())
        for match in evm_matches
    ]

    for match in evm_matches:
        address = match.group(0)

        key = (
            "evm",
            address.lower()
        )

        if key in seen:
            continue

        seen.add(key)

        contracts.append({
            "chain": "evm",
            "address": address,
        })

    # -------------------------
    # Solana
    # -------------------------

    for match in SOLANA_PATTERN.finditer(content):
        address = match.group(0)

        # Prevent interpreting part of an EVM
        # address as a Solana address.
        overlaps_evm = any(
            match.start() < end
            and match.end() > start
            for start, end in evm_ranges
        )

        if overlaps_evm:
            continue

        if not is_valid_solana_address(address):
            continue

        key = (
            "solana",
            address
        )

        if key in seen:
            continue

        seen.add(key)

        contracts.append({
            "chain": "solana",
            "address": address,
        })

    return contracts