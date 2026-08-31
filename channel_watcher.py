import os
import json
import time
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

from avanak import trigger_phone_alarm
from contract_detector import find_contracts


# =========================================================
# Configuration
# =========================================================

load_dotenv()

CHANNEL = os.getenv("TELEGRAM_CHANNEL")

if not CHANNEL:
    raise RuntimeError(
        "TELEGRAM_CHANNEL is missing from .env"
    )

CHANNEL = CHANNEL.lstrip("@")

URL = f"https://t.me/s/{CHANNEL}"

POLL_INTERVAL = 1.0


# Each channel has its own files
STATE_FILE = f"state_{CHANNEL}.json"
CONTRACTS_FILE = f"contracts_{CHANNEL}.json"

LOG_DIR = "logs"

LOG_FILE = os.path.join(
    LOG_DIR,
    f"{CHANNEL}.log"
)


# =========================================================
# HTTP Session
# =========================================================

session = requests.Session()

session.headers.update({
    "User-Agent": (
        "Mozilla/5.0 "
        "(Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "Chrome/120 Safari/537.36"
    ),
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
})


# =========================================================
# Utilities
# =========================================================

def utc_now():
    return datetime.now(timezone.utc)


def format_time(dt):
    if not dt:
        return "unknown"

    return dt.isoformat(
        timespec="milliseconds"
    )


def log(message):
    os.makedirs(
        LOG_DIR,
        exist_ok=True
    )

    line = (
        f"[{format_time(utc_now())}] "
        f"{message}"
    )

    print(line)

    with open(
        LOG_FILE,
        "a",
        encoding="utf-8"
    ) as file:
        file.write(line + "\n")


# =========================================================
# Telegram Message State
# =========================================================

def load_last_message_id():

    if not os.path.exists(STATE_FILE):
        return None

    try:

        with open(
            STATE_FILE,
            "r",
            encoding="utf-8"
        ) as file:

            data = json.load(file)

        return int(
            data["last_message_id"]
        )

    except Exception as error:

        log(
            f"⚠️ Could not read state: {error}"
        )

        return None


def save_last_message_id(message_id):

    data = {
        "channel": CHANNEL,
        "last_message_id": message_id,
        "updated_at": format_time(
            utc_now()
        ),
    }

    temp_file = (
        STATE_FILE + ".tmp"
    )

    with open(
        temp_file,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            data,
            file,
            ensure_ascii=False,
            indent=2,
        )

    os.replace(
        temp_file,
        STATE_FILE
    )


# =========================================================
# Contract Database
# =========================================================

def contract_key(chain, address):
    """
    Generate a unique key.

    EVM addresses are case-insensitive.
    Solana addresses are case-sensitive.
    """

    if chain.lower() == "evm":
        address = address.lower()

    return f"{chain.lower()}:{address}"


def load_seen_contracts():

    if not os.path.exists(CONTRACTS_FILE):
        return {}

    try:

        with open(
            CONTRACTS_FILE,
            "r",
            encoding="utf-8"
        ) as file:

            data = json.load(file)

        if not isinstance(data, dict):
            return {}

        return data

    except Exception as error:

        log(
            f"⚠️ Could not read contracts database: "
            f"{error}"
        )

        return {}


def save_seen_contracts(contracts_db):

    temp_file = (
        CONTRACTS_FILE + ".tmp"
    )

    with open(
        temp_file,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            contracts_db,
            file,
            ensure_ascii=False,
            indent=2,
        )

    # Atomic replacement
    os.replace(
        temp_file,
        CONTRACTS_FILE
    )


def register_contracts(
    contracts,
    message,
    contracts_db
):
    """
    Save contracts after a successful alert.
    """

    now = format_time(
        utc_now()
    )

    for contract in contracts:

        chain = contract["chain"]
        address = contract["address"]

        key = contract_key(
            chain,
            address
        )

        if key in contracts_db:
            continue

        contracts_db[key] = {
            "chain": chain,
            "address": address,
            "first_message_id": message["id"],
            "first_seen_at": now,
            "telegram_post": message["post"],
        }

    save_seen_contracts(
        contracts_db
    )


# =========================================================
# Telegram Parsing
# =========================================================

def parse_telegram_datetime(message):

    time_element = (
        message.select_one("time")
    )

    if not time_element:
        return None

    raw_datetime = (
        time_element.get("datetime")
    )

    if not raw_datetime:
        return None

    try:

        return datetime.fromisoformat(
            raw_datetime.replace(
                "Z",
                "+00:00"
            )
        )

    except ValueError:
        return None


def extract_links(element):
    """
    Extract URLs from the Telegram post.

    Important because a CA might only
    exist inside a Dexscreener/Pump.fun URL.
    """

    links = []

    for anchor in element.select("a[href]"):

        href = anchor.get("href")

        if href:
            links.append(href)

    return links


def get_messages():

    response = session.get(
        URL,
        timeout=10
    )

    response.raise_for_status()

    soup = BeautifulSoup(
        response.text,
        "html.parser"
    )

    elements = soup.select(
        ".tgme_widget_message[data-post]"
    )

    messages = []

    for element in elements:

        data_post = element.get(
            "data-post"
        )

        if not data_post:
            continue

        try:

            message_id = int(
                data_post.rsplit(
                    "/",
                    1
                )[1]
            )

        except (
            IndexError,
            ValueError
        ):
            continue

        text_element = (
            element.select_one(
                ".tgme_widget_message_text"
            )
        )

        if text_element:

            text = (
                text_element.get_text(
                    " ",
                    strip=True
                )
            )

        else:
            text = ""

        links = extract_links(
            element
        )

        # Contract detector checks both
        # visible text and hidden URLs.
        detection_content = (
            text
            + "\n"
            + "\n".join(links)
        )

        published_at = (
            parse_telegram_datetime(
                element
            )
        )

        messages.append({
            "id": message_id,
            "text": text,
            "links": links,
            "detection_content": (
                detection_content
            ),
            "post": data_post,
            "published_at": (
                published_at
            ),
        })

    messages.sort(
        key=lambda item: item["id"]
    )

    return messages


# =========================================================
# Message Processing
# =========================================================

def process_message(
    message,
    contracts_db
):

    detected_at = utc_now()

    published_at = (
        message["published_at"]
    )

    if (
        published_at
        and published_at.tzinfo is None
    ):

        published_at = (
            published_at.replace(
                tzinfo=timezone.utc
            )
        )

    detection_latency = None

    if published_at:

        detection_latency = (
            detected_at
            - published_at
        ).total_seconds()

    print()
    print("=" * 75)

    log("📨 NEW TELEGRAM POST")

    log(
        f"Channel: @{CHANNEL}"
    )

    log(
        f"Message ID: "
        f"{message['id']}"
    )

    if message["text"]:

        log(
            f"Text: "
            f"{message['text']}"
        )

    else:

        log(
            "Text: [No text]"
        )

    log(
        "Telegram published: "
        f"{format_time(published_at)}"
    )

    log(
        "Detected by watcher: "
        f"{format_time(detected_at)}"
    )

    if detection_latency is not None:

        log(
            "Telegram → detection latency: "
            f"{detection_latency:.3f}s"
        )

    # Message itself is considered processed.
    save_last_message_id(
        message["id"]
    )

    # =====================================================
    # Detect Contracts
    # =====================================================

    contracts = find_contracts(
        message["detection_content"]
    )

    if not contracts:

        log(
            "⏭️ No EVM/Solana contract "
            "detected."
        )

        print("=" * 75)
        print()

        return

    log(
        f"🔎 Contract candidates: "
        f"{len(contracts)}"
    )

    # =====================================================
    # Remove Contracts Seen Before
    # =====================================================

    new_contracts = []

    duplicate_contracts = []

    for contract in contracts:

        key = contract_key(
            contract["chain"],
            contract["address"]
        )

        if key in contracts_db:

            duplicate_contracts.append(
                contract
            )

        else:

            new_contracts.append(
                contract
            )

    # Print duplicates
    for contract in duplicate_contracts:

        log(
            f"♻️ Already seen "
            f"{contract['chain'].upper()}: "
            f"{contract['address']}"
        )

    # Nothing new
    if not new_contracts:

        log(
            "⏭️ All detected contracts "
            "were already seen."
        )

        log(
            "📵 No phone call."
        )

        print("=" * 75)
        print()

        return

    # =====================================================
    # New Contract Found
    # =====================================================

    log(
        f"🚨 NEW CONTRACT(S): "
        f"{len(new_contracts)}"
    )

    for contract in new_contracts:

        log(
            f"🆕 "
            f"{contract['chain'].upper()}: "
            f"{contract['address']}"
        )

    # =====================================================
    # Trigger Phone Alarm
    # =====================================================

    call_started_at = utc_now()

    log(
        "📞 Avanak request started: "
        f"{format_time(call_started_at)}"
    )

    try:

        result = (
            trigger_phone_alarm()
        )

        call_finished_at = (
            utc_now()
        )

        log(
            "✅ Avanak accepted request"
        )

        quick_send_id = (
            result["result"].get(
                "QuickSendID"
            )
        )

        generated_code = (
            result["result"].get(
                "GeneratedCode"
            )
        )

        log(
            f"QuickSendID: "
            f"{quick_send_id}"
        )

        log(
            f"GeneratedCode: "
            f"{generated_code}"
        )

        log(
            "Avanak API response time: "
            f"{result['response_time']:.3f}s"
        )

        if published_at:

            total_latency = (
                call_finished_at
                - published_at
            ).total_seconds()

            log(
                "Telegram post → "
                "Avanak accepted: "
                f"{total_latency:.3f}s"
            )

        # =================================================
        # Save contracts ONLY after Avanak accepts the call
        # =================================================

        register_contracts(
            new_contracts,
            message,
            contracts_db
        )

        log(
            f"💾 Saved "
            f"{len(new_contracts)} "
            f"new contract(s)"
        )

    except Exception as error:

        log(
            f"❌ Phone alarm failed: "
            f"{error}"
        )

        log(
            "⚠️ Contracts were NOT saved "
            "because the call failed."
        )

    print("=" * 75)
    print()


# =========================================================
# Main
# =========================================================

def main():

    log(
        f"👀 Watching @{CHANNEL}"
    )

    log(
        f"Telegram URL: {URL}"
    )

    log(
        f"State file: "
        f"{STATE_FILE}"
    )

    log(
        f"Contract database: "
        f"{CONTRACTS_FILE}"
    )

    # Load persistent contract history
    contracts_db = (
        load_seen_contracts()
    )

    log(
        f"🗃️ Known contracts: "
        f"{len(contracts_db)}"
    )

    messages = get_messages()

    if not messages:

        raise RuntimeError(
            f"No messages found "
            f"in @{CHANNEL}"
        )

    current_latest_id = (
        messages[-1]["id"]
    )

    saved_message_id = (
        load_last_message_id()
    )

    if saved_message_id is None:

        # First startup:
        # ignore previous Telegram posts
        last_message_id = (
            current_latest_id
        )

        save_last_message_id(
            last_message_id
        )

        log(
            "First startup for "
            "this channel."
        )

        log(
            f"Baseline message ID: "
            f"{last_message_id}"
        )

    else:

        last_message_id = (
            saved_message_id
        )

        log(
            "Loaded existing state."
        )

        log(
            "Last processed message ID: "
            f"{last_message_id}"
        )

    log(
        "✅ Watcher ready."
    )

    log(
        "📡 Waiting for NEW "
        "EVM/Solana contracts..."
    )

    while True:

        try:

            messages = get_messages()

            new_messages = [
                message
                for message in messages
                if (
                    message["id"]
                    > last_message_id
                )
            ]

            for message in new_messages:

                process_message(
                    message,
                    contracts_db
                )

                last_message_id = (
                    message["id"]
                )

        except requests.RequestException as error:

            log(
                "⚠️ Telegram request error: "
                f"{error}"
            )

            time.sleep(5)

        except Exception as error:

            log(
                f"⚠️ Watcher error: "
                f"{error}"
            )

            time.sleep(3)

        time.sleep(
            POLL_INTERVAL
        )


if __name__ == "__main__":
    main()