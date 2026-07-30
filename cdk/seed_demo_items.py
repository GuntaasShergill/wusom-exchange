"""
Seed script - inserts demo items directly into the deployed DynamoDB table,
matching the exact schema the Items Lambda writes (see lambda/items/handler.py).

Usage:
    pip install boto3 --break-system-packages   # if not already installed
    python3 seed_demo_items.py --table wusom-exchange-dev --owner mirzah@wustl.edu

Requires AWS credentials configured locally (same ones `cdk deploy` used) and
the table already deployed.
"""
import argparse
import uuid
import boto3
from datetime import datetime, timezone

DEMO_ITEMS = [
    {
        "title": "Eppendorf 5810R Centrifuge (24-slot)",
        "category": "lab-equipment",
        "description": "Works great, upgrading to a newer model. Pickup from Olin Hall rm 214.",
    },
    {
        "title": "Box of unopened PCR tubes (0.2mL, 1000ct)",
        "category": "reagents",
        "description": "Ordered too many for a grant that got cut. Sealed box.",
    },
    {
        "title": "Adjustable lab stool",
        "category": "furniture",
        "description": "Good condition, minor scuff on one leg.",
    },
    {
        "title": "24-inch monitor, HDMI",
        "category": "electronics",
        "description": "Dell, works fine, replaced with dual-monitor setup.",
    },
    {
        "title": "-80C freezer rack dividers (set of 6)",
        "category": "lab-equipment",
        "description": "Fit standard Thermo Fisher -80 units. No longer needed after freezer swap.",
    },
]


def seed(table_name: str, owner_email: str):
    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(table_name)

    for item in DEMO_ITEMS:
        item_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        table.put_item(Item={
            "PK": f"ITEM#{item_id}",
            "SK": f"ITEM#{item_id}",
            "GSI1PK": f"CATEGORY#{item['category']}",
            "GSI1SK": now,
            "GSI2PK": "ITEM",
            "GSI2SK": now,
            "item_id": item_id,
            "title": item["title"],
            "category": item["category"],
            "description": item["description"],
            "owner_email": owner_email,
            "status": "available",
            "created_at": now,
        })
        print(f"Seeded: {item['title']} ({item_id})")

    print(f"\nDone. {len(DEMO_ITEMS)} items seeded, owned by {owner_email}.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--table", required=True, help="DynamoDB table name (the TableName CDK output)")
    parser.add_argument("--owner", required=True, help="Email to set as owner_email on seeded items")
    args = parser.parse_args()
    seed(args.table, args.owner)