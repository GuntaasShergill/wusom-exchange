# WUSOMExchange

This is a market-place designed for Researchers at WashU (having the email from domain @wustl.edu) to freely exchange spare equipment/reagents/furniture. This service includes a weekly email digest which goes out to subscribers via SES. 

The rationale for the architecture is included in ADR.dcox, for this README I will focus on how to set up this architecture for execution. 

## Architecture

```
User Browser
     |
     v
CloudFront + S3
(Website)
     |
     v
Cognito Login
(WUSTL users only)
     |
     v
API Gateway
     |
     ------------------
     |                |
     v                v
Items Lambda     Newsletter Lambda
     |                |
     |                v
     |              SES
     |          (send emails)
     |
     v
DynamoDB
(items + users)

     ^
     |
EventBridge
(every week; 7 days)
```

## Repo layout

```
cdk/                 
  app.py
  stacks/wusom_stack.py
lambda/
  items/handler.py       GET/POST /items (create, claim, browse)
  subscribe/handler.py   POST /subscribe, GET /unsubscribe
  newsletter/handler.py  EventBridge-based weekly digest
  pre_signup/handler.py  Cognito restricting sign-up to @wustl.edu
frontend/              Site deployed to S3 ; CloudFront
.github/workflows/     For storage of automation workflows
```

## Prerequisites
- The user is expected to have an AWS account and credentials pre-configured (via aws configure) and all permissions
- User must have Node.js, AWS CDK, and Python 3.12
- User needs and email address for verification in SES

## Deploy (for first time deployment)

```bash
cd cdk # we will need first change into the cdk folder WITHIN the WUSOMExchange parent folder
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cdk bootstrap

# deploy the dev stage, remember to tweak the email address
cdk deploy -c stage=dev -c ses_sender_email=[insert id here]@wustl.edu
```

Upon completion of this step we will receive the following terminal output, which is required for the next two steps: 
- APIUrl
- SiteUrl
- UserPoolId
- UserPoolClientId
- CognitoDomain

### 1. Verify the SES sender identity

For first time start up we will need to confirm the verification link AQS sends us, otherwise Sending Emails will fail. 

### 2. Wire up the frontend config

We need to edit frontend/config.js with the values from the CDK output as explained above:

```js
window.WUSOM_CONFIG = {
  apiUrl: "<ApiUrl output, no trailing slash>",
  cognitoDomain: "https://<CognitoDomain output>.auth.<region>.amazoncognito.com",
  userPoolClientId: "<UserPoolClientId output>",
  redirectUri: "<SiteUrl output>/index.html",
};
```

### 3. Wire up the Cognito callback URL

The User Pool Client is created with `http://localhost:5500/index.html` as a
placeholder callback/logout URL. Update it to the real site URL, in the AWS
Console (Cognito -> User pools -> your pool -> App integration -> your app
client -> Edit hosted UI settings)

### 4. Redeploy the frontend with the real config

```bash
cdk deploy -c stage=dev
```

`BucketDeployment` re-uploads `frontend/` and invalidates CloudFront automatically.

## Teardown

```bash
cdk destroy -c stage=dev
```
