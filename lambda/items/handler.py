"""
Items Lambda
  GET  /items            -> public browse. Optional ?category=<cat> uses GSI1.
  POST /items             -> requires Cognito auth (JWT claims give owner email).

Table layout (single table):
  PK = ITEM#<item_id>   SK = ITEM#<item_id>
  GSI1PK = CATEGORY#<category>   GSI1SK = created_at   (browse by category)
  GSI2PK = ITEM                  GSI2SK = created_at   (newsletter: items since last send)
"""
import json
import os
import uuid
import boto3
from datetime import datetime, timezone
from boto3.dynamodb.conditions import Key

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(os.environ["TABLE_NAME"])

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
}


def _resp(status, body):
    return {"statusCode": status, "headers": CORS_HEADERS, "body": json.dumps(body)}


def handler(event, context):
    method = event.get("httpMethod")
    if method == "GET":
        return _list_items(event)
    if method == "POST":
        return _write_item(event)
    return _resp(405, {"error": "method not allowed"})


def _list_items(event):
    category = (event.get("queryStringParameters") or {}).get("category")
    if category:
        result = table.query(
            IndexName="GSI1-CategoryBrowse",
            KeyConditionExpression=Key("GSI1PK").eq(f"CATEGORY#{category}"),
            ScanIndexForward=False,
        )
    else:
        result = table.query(
            IndexName="GSI2-RecentItems",
            KeyConditionExpression=Key("GSI2PK").eq("ITEM"),
            ScanIndexForward=False,
            Limit=100,
        )
    items = [_public_item(i) for i in result.get("Items", [])]
    return _resp(200, {"items": items})


def _public_item(i):
    return {
        "item_id": i["item_id"],
        "title": i["title"],
        "category": i["category"],
        "description": i.get("description", ""),
        "status": i.get("status", "available"),
        "created_at": i.get("created_at"),
    }


def _write_item(event):
    claims = _get_claims(event)
    owner_email = claims.get("email")
    if not owner_email:
        return _resp(401, {"error": "unauthorized"})

    body = json.loads(event.get("body") or "{}")
    action = body.get("action")

    if action == "create":
        title = body.get("title")
        category = body.get("category")
        if not title or not category:
            return _resp(400, {"error": "title and category are required"})

        item_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        table.put_item(Item={
            "PK": f"ITEM#{item_id}",
            "SK": f"ITEM#{item_id}",
            "GSI1PK": f"CATEGORY#{category}",
            "GSI1SK": now,
            "GSI2PK": "ITEM",
            "GSI2SK": now,
            "item_id": item_id,
            "title": title,
            "category": category,
            "description": body.get("description", ""),
            "owner_email": owner_email,
            "status": "available",
            "created_at": now,
        })
        return _resp(201, {"item_id": item_id, "status": "available"})

    if action == "claim":
        item_id = body.get("item_id")
        if not item_id:
            return _resp(400, {"error": "item_id is required"})
        try:
            table.update_item(
                Key={"PK": f"ITEM#{item_id}", "SK": f"ITEM#{item_id}"},
                UpdateExpression="SET #s = :claimed, claimed_by = :who, claimed_at = :when",
                ConditionExpression="attribute_exists(PK) AND #s = :available",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={
                    ":claimed": "claimed",
                    ":available": "available",
                    ":who": owner_email,
                    ":when": datetime.now(timezone.utc).isoformat(),
                },
            )
        except dynamodb.meta.client.exceptions.ConditionalCheckFailedException:
            return _resp(409, {"error": "item already claimed or does not exist"})
        return _resp(200, {"item_id": item_id, "status": "claimed"})

    return _resp(400, {"error": "unknown action"})


def _get_claims(event):
    return (
        event.get("requestContext", {})
        .get("authorizer", {})
        .get("claims", {})
    ) or {}
