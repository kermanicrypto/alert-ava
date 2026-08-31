import os
import json
import time
import requests
from dotenv import load_dotenv


load_dotenv()

TOKEN = os.getenv("AVANAK_TOKEN")
PHONE_NUMBER = os.getenv("PHONE_NUMBER")

URL = "https://portal.avanak.ir/Rest/SendOTP"


def trigger_phone_alarm():

    if not TOKEN:
        raise RuntimeError("AVANAK_TOKEN is missing from .env")

    if not PHONE_NUMBER:
        raise RuntimeError("PHONE_NUMBER is missing from .env")

    headers = {
        "Authorization": TOKEN,
        "Content-Type": "application/x-www-form-urlencoded",
    }

    # همان payload که قبلاً موفق شد
    payload = {
        "Length": "4",
        "Number": PHONE_NUMBER,
        "ServerID": "0",
    }

    print("📞 Sending Avanak OTP call...")

    started = time.time()

    response = requests.post(
        URL,
        headers=headers,
        data=payload,
        timeout=30,
    )

    elapsed = time.time() - started

    print(f"HTTP status: {response.status_code}")
    print(f"API response time: {elapsed:.3f}s")

    try:
        result = response.json()

        print("Avanak response:")
        print(
            json.dumps(
                result,
                ensure_ascii=False,
                indent=2
            )
        )

    except ValueError:
        print("Raw response:")
        print(response.text)

        raise RuntimeError(
            "Avanak returned invalid JSON"
        )

    if (
        response.status_code == 200
        and result.get("ErrorCode") == 0
    ):
        print("✅ Avanak accepted the call")
        print(
            "QuickSendID:",
            result.get("QuickSendID")
        )
        print(
            "GeneratedCode:",
            result.get("GeneratedCode")
        )

        return {
            "success": True,
            "result": result,
            "response_time": elapsed,
            "attempt": 1,
        }

    raise RuntimeError(
        f"Avanak call failed: {result}"
    )


# اجازه می‌دهد خود avanak.py را جداگانه تست کنیم
if __name__ == "__main__":
    trigger_phone_alarm()