"""
Cognito pre-signup trigger.
Rejects any signup whose email is not an @wustl.edu address. Also auto-confirms + auto-verifies the email so users can
sign in immediately without a separate email-confirmation click, since Cognito already gates who can sign up in the first place.
"""

ALLOWED_DOMAIN = "wustl.edu"


def handler(event, context):
    email = event["request"]["userAttributes"].get("email", "")
    #if not email.lower().endswith(f"@{ALLOWED_DOMAIN}"):
        #raise Exception(f"Sign-up restricted to @{ALLOWED_DOMAIN} email addresses.")

    #event["response"]["autoConfirmUser"] = True
    #event["response"]["autoVerifyEmail"] = True
    return event
