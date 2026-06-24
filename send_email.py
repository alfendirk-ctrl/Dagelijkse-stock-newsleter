#!/usr/bin/env python3
"""
Stap 3: leest email_final.html en verstuurt via Gmail SMTP.
Vereist: GMAIL_USER en GMAIL_APP_PASSWORD env vars.
"""

import os
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

DUTCH_MONTHS = {
    1: "januari", 2: "februari", 3: "maart", 4: "april",
    5: "mei", 6: "juni", 7: "juli", 8: "augustus",
    9: "september", 10: "oktober", 11: "november", 12: "december",
}

TO = "alfendirk@gmail.com"


def main():
    gmail_user = os.environ.get("GMAIL_USER", "")
    # Strip spaties — app passwords worden soms met spaties gekopieerd
    gmail_pw = "".join(os.environ.get("GMAIL_APP_PASSWORD", "").split())

    if not gmail_user or not gmail_pw:
        print("❌ GMAIL_USER of GMAIL_APP_PASSWORD niet gevonden")
        raise SystemExit(1)

    with open("email_final.html", "r", encoding="utf-8") as f:
        html_body = f.read()

    n = datetime.now()
    today = f"{n.day} {DUTCH_MONTHS[n.month]} {n.year}"
    subject = f"📌 Dagelijkse beursupdate – {today}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = gmail_user
    msg["To"] = TO
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(gmail_user, gmail_pw)
            server.sendmail(gmail_user, TO, msg.as_string())
        print(f"✅ Email verzonden naar {TO}")
    except smtplib.SMTPAuthenticationError as e:
        print(f"❌ Authenticatiefout — controleer Gmail App Password: {e}")
        raise SystemExit(1)
    except Exception as e:
        print(f"❌ Versturen mislukt: {e}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
