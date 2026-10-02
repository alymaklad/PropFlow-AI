#!/usr/bin/env python3
"""Simulate a customer email to the leads inbox (GreenMail SMTP on localhost, dev only).

  python3 scripts/send_email.py --from buyer@example.com --name "Buyer" \
      --subject "Villa in Sheikh Zayed" --body "4 bedrooms, up to 15M, buying in 2 months"
  python3 scripts/send_email.py --from buyer@example.com --subject "Re: Listings" \
      --body "Can we visit on Tuesday?" --in-reply-to "<message-id-of-our-email>"
"""

import argparse
import os
import smtplib
from email.message import EmailMessage
from email.utils import make_msgid


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--from", dest="sender", required=True)
    parser.add_argument("--name", default="")
    parser.add_argument("--to", default=os.environ.get("INBOUND_EMAIL", "leads@propflow.test"))
    parser.add_argument("--subject", required=True)
    parser.add_argument("--body", required=True)
    parser.add_argument("--in-reply-to", help="Message-ID of the email being answered")
    parser.add_argument("--port", type=int,
                        default=int(os.environ.get("GREENMAIL_SMTP_PORT", 3025)))
    args = parser.parse_args()

    msg = EmailMessage()
    msg["From"] = f"{args.name} <{args.sender}>" if args.name else args.sender
    msg["To"] = args.to
    msg["Subject"] = args.subject
    msg["Message-ID"] = make_msgid(domain="customer.example.com")
    if args.in_reply_to:
        msg["In-Reply-To"] = args.in_reply_to
        msg["References"] = args.in_reply_to
    msg.set_content(args.body)
    with smtplib.SMTP("127.0.0.1", args.port, timeout=15) as smtp:
        smtp.send_message(msg)
    print("sent", msg["Message-ID"])


if __name__ == "__main__":
    main()
