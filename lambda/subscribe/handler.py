"""
Subscribe Lambda
  POST /subscribe:          -> requires Cognito auth. Adds/reactivates the
                               caller's email as an active newsletter subscriber.
  GET  /unsubscribe?token=  -> public. No Cognito authorizer,
                               unsubscribe is a plain link clicked from the
                               email itself, so it can't require a login.

Table layout (single table, reuses GSI1 with a different key namespace
than the "items" use of GSI1 - CATEGORY# vs TOKEN# prefixes never collide):
  PK = SUB#<email>   SK = SUB#<email>
  GSI1PK = TOKEN#<unsubscribe_token>   GSI1SK = SUB#<email>
"""
import json
import os
import secrets
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


def _resp(status, body, content_type="application/json"):
    return {
        "statusCode": status,
        "headers": {**CORS_HEADERS, "Content-Type": content_type},
        "body": body if content_type != "application/json" else json.dumps(body),
    }


def handler(event, context):
    method = event.get("httpMethod")
    if method == "POST":
        return _subscribe(event)
    if method == "GET":
        return _unsubscribe(event)
    return _resp(405, {"error": "method not allowed"})


def _subscribe(event):
    claims = (
        event.get("requestContext", {}).get("authorizer", {}).get("claims", {})
    ) or {}
    email = claims.get("email")
    if not email:
        return _resp(401, {"error": "unauthorized"})

    token = secrets.token_urlsafe(24)
    now = datetime.now(timezone.utc).isoformat()
    table.put_item(Item={
        "PK": f"SUB#{email}",
        "SK": f"SUB#{email}",
        "GSI1PK": f"TOKEN#{token}",
        "GSI1SK": f"SUB#{email}",
        "email": email,
        "active": True,
        "unsubscribe_token": token,
        "subscribed_at": now,
    })
    return _resp(201, {"email": email, "status": "subscribed"})


def _unsubscribe(event):
    token = (event.get("queryStringParameters") or {}).get("token")
    if not token:
        return _resp(400, "Missing unsubscribe token.", content_type="text/html")

    result = table.query(
        IndexName="GSI1-CategoryBrowse",
        KeyConditionExpression=Key("GSI1PK").eq(f"TOKEN#{token}"),
    )
    items = result.get("Items", [])
    if not items:
        return _resp(404, "Unsubscribe link not recognized.", content_type="text/html")

    email = items[0]["email"]
    table.update_item(
        Key={"PK": f"SUB#{email}", "SK": f"SUB#{email}"},
        UpdateExpression="SET active = :inactive",
        ExpressionAttributeValues={":inactive": False},
    )
    return _resp(
        200,
        f"<html><body><h2>You've been unsubscribed</h2>"
        f"<p>{email} will no longer receive the WUSOMExchange newsletter.</p></body></html>",
        content_type="text/html",
    )
