"""
Newsletter Lambda invoked on a schedule (EventBridge Scheduler, rate: 7 days).

Steps:
  1. Read CONFIG#NEWSLETTER for the last-sent timestamp.
  2. Query GSI2 (GSI2PK = "ITEM") for items created since then.
  3. If there are no new items, skip sending entirely
  4. Scan for active subscribers (PK begins_with SUB#, active = true)
  5. Send one SES email per active subscriber with an unsubscribe link
     unique to that subscriber's token.
  6. Update the last-sent marker.
"""
import os
import boto3
from datetime import datetime, timezone
from boto3.dynamodb.conditions import Key, Attr

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(os.environ["TABLE_NAME"])
ses = boto3.client("ses")

SENDER_EMAIL = os.environ.get("SENDER_EMAIL", "newsletter@example.com")
CONFIG_KEY = {"PK": "CONFIG#NEWSLETTER", "SK": "CONFIG#NEWSLETTER"}
UNSUBSCRIBE_BASE_URL = os.environ.get(
    "UNSUBSCRIBE_BASE_URL", "https://example.execute-api.us-east-2.amazonaws.com/prod/unsubscribe"
)

def handler(event, context):
    last_sent_at = _get_last_sent_at()
    new_items = _get_items_since(last_sent_at)

    if not new_items:
        print("No new items since last newsletter - skipping send.")
        return {"sent": False, "reason": "no new items"}

    subscribers = _get_active_subscribers()
    if not subscribers:
        print("No active subscribers - skipping send.")
        _update_last_sent_at()
        return {"sent": False, "reason": "no subscribers"}

    body_html = _build_email_body(new_items)

    for sub in subscribers:
        unsubscribe_link = f"{UNSUBSCRIBE_BASE_URL}?token={sub['unsubscribe_token']}"
        ses.send_email(
            Source=SENDER_EMAIL,
            Destination={"ToAddresses": [sub["email"]]},
            Message={
                "Subject": {"Data": "WUSOMExchange Weekly Digest"},
                "Body": {"Html": {"Data": body_html + _unsubscribe_footer(unsubscribe_link)}},
            },
        )

    _update_last_sent_at()
    return {"sent": True, "items": len(new_items), "recipients": len(subscribers)}


def _get_last_sent_at():
    result = table.get_item(Key=CONFIG_KEY)
    item = result.get("Item")
    return item["last_sent_at"] if item else "1970-01-01T00:00:00+00:00"


def _update_last_sent_at():
    now = datetime.now(timezone.utc).isoformat()
    table.put_item(Item={**CONFIG_KEY, "last_sent_at": now})


def _get_items_since(last_sent_at):
    result = table.query(
        IndexName="GSI2-RecentItems",
        KeyConditionExpression=Key("GSI2PK").eq("ITEM") & Key("GSI2SK").gt(last_sent_at),
    )
    return result.get("Items", [])


def _get_active_subscribers():
    result = table.scan(
        FilterExpression=Attr("PK").begins_with("SUB#") & Attr("active").eq(True)
    )
    return result.get("Items", [])


def _build_email_body(items):
    rows = "".join(
        f"<li><strong>{i['title']}</strong> ({i['category']}) - {i.get('description', '')}</li>"
        for i in items
    )
    return f"<html><body><h2>New items this week</h2><ul>{rows}</ul>"


def _unsubscribe_footer(link):
    return f'<p style="font-size:12px;color:#666"><a href="{link}">Unsubscribe</a></p></body></html>'
