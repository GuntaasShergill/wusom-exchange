from aws_cdk import (
    Stack, Duration, RemovalPolicy, CfnOutput,
    aws_dynamodb as ddb,
    aws_lambda as _lambda,
    aws_apigateway as apigw,
    aws_cognito as cognito,
    aws_s3 as s3,
    aws_s3_deployment as s3deploy,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    aws_scheduler as scheduler,
    aws_iam as iam,
    aws_ses as ses,
)
from constructs import Construct

class WusomExchangeStack(Stack):
    """
    WUSOMExchange - it contains: 
    - single-table DynamoDB
    - Lambda-behind-API-Gateway,
    - Cognito-gated writes
    - EventBridge Scheduler
    - SES newsletter.
    See ADR.docx in the submission for the reasoning behind each choice stated above.
    """

    def __init__(self, scope: Construct, construct_id: str, *, stage: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.stage = stage
        removal_policy = RemovalPolicy.DESTROY

        # ------------------------------------------------------------------
        # DynamoDB : single table, two GSIs
        #   PK/SK          -> ITEM#<id> / ITEM#<id>      (item records)
        #                     SUB#<email> / SUB#<email>  (subscriber records)
        #                     CONFIG#NEWSLETTER / CONFIG#NEWSLETTER (last-sent marker)
        #   GSI1 (browse)  -> GSI1PK = CATEGORY#<cat>, GSI1SK = created_at  (browse by category)
        #   GSI2 (recency) -> GSI2PK = "ITEM",         GSI2SK = created_at  (newsletter: items since last send)
        # ------------------------------------------------------------------
        table = ddb.Table(
            self, "WusomTable",
            table_name=f"wusom-exchange-{stage}",
            partition_key=ddb.Attribute(name="PK", type=ddb.AttributeType.STRING),
            sort_key=ddb.Attribute(name="SK", type=ddb.AttributeType.STRING),
            billing_mode=ddb.BillingMode.PAY_PER_REQUEST,
            removal_policy=removal_policy,
        )
        table.add_global_secondary_index(
            index_name="GSI1-CategoryBrowse",
            partition_key=ddb.Attribute(name="GSI1PK", type=ddb.AttributeType.STRING),
            sort_key=ddb.Attribute(name="GSI1SK", type=ddb.AttributeType.STRING),
        )
        table.add_global_secondary_index(
            index_name="GSI2-RecentItems",
            partition_key=ddb.Attribute(name="GSI2PK", type=ddb.AttributeType.STRING),
            sort_key=ddb.Attribute(name="GSI2SK", type=ddb.AttributeType.STRING),
        )

        # ------------------------------------------------------------------
        # Cognito:
        # - restricted to @wustl.edu via pre-signup Lambda trigger
        # ------------------------------------------------------------------
        pre_signup_fn = _lambda.Function(
            self, "PreSignUpFn",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="handler.handler",
            code=_lambda.Code.from_asset("../lambda/pre_signup"),
            timeout=Duration.seconds(10),
        )

        user_pool = cognito.UserPool(
            self, "WusomUserPool",
            user_pool_name=f"wusom-users-{stage}",
            self_sign_up_enabled=True,
            sign_in_aliases=cognito.SignInAliases(email=True),
            auto_verify=cognito.AutoVerifiedAttrs(email=True),
            password_policy=cognito.PasswordPolicy(
                min_length=8,
                require_lowercase=True,
                require_uppercase=False,
                require_digits=True,
                require_symbols=False,
            ),
            lambda_triggers=cognito.UserPoolTriggers(pre_sign_up=pre_signup_fn),
            removal_policy=removal_policy,
        )

        # This is a fixed prefix. If `cdk deploy` reports it's taken, override
        # with `-c domain_prefix=wusom-exchange-<yournetid>-<stage>`.
        domain_prefix = self.node.try_get_context("domain_prefix") or f"wusom-exchange-{stage}"
        user_pool_domain = user_pool.add_domain(
            "WusomUserPoolDomain",
            cognito_domain=cognito.CognitoDomainOptions(domain_prefix=domain_prefix.lower()),
        )

        user_pool_client = user_pool.add_client(
            "WusomUserPoolClient",
            generate_secret=False,
            o_auth=cognito.OAuthSettings(
                flows=cognito.OAuthFlows(implicit_code_grant=True),

                scopes=[cognito.OAuthScope.EMAIL, cognito.OAuthScope.OPENID, cognito.OAuthScope.PROFILE],
                # CloudFront URL is only known after the distribution is created below;
                # update these callback URLs post-deploy (see README "Wire up Cognito callback URLs").
                callback_urls=["http://localhost:5500/index.html"],
                logout_urls=["http://localhost:5500/index.html"],
            ),
        )

        authorizer = apigw.CognitoUserPoolsAuthorizer(
            self, "WusomAuthorizer",
            cognito_user_pools=[user_pool],
        )

        # ------------------------------------------------------------------
        # SES : identity for the "from" address used by the newsletter
        # ------------------------------------------------------------------
        sender_email = self.node.try_get_context("ses_sender_email") or "newsletter@example.com"
        ses.EmailIdentity(
            self, "NewsletterSenderIdentity",
            identity=ses.Identity.email(sender_email),
        )

        # ------------------------------------------------------------------
        # Lambdas
        # ------------------------------------------------------------------
        common_env = {"TABLE_NAME": table.table_name, "STAGE": stage}

        items_fn = _lambda.Function(
            self, "ItemsFn",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="handler.handler",
            code=_lambda.Code.from_asset("../lambda/items"),
            environment=common_env,
            timeout=Duration.seconds(10),
            memory_size=256,
        )
        table.grant_read_write_data(items_fn)

        subscribe_fn = _lambda.Function(
            self, "SubscribeFn",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="handler.handler",
            code=_lambda.Code.from_asset("../lambda/subscribe"),
            environment=common_env,
            timeout=Duration.seconds(10),
            memory_size=256,
        )
        table.grant_read_write_data(subscribe_fn)

        newsletter_fn = _lambda.Function(
            self, "NewsletterFn",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="handler.handler",
            code=_lambda.Code.from_asset("../lambda/newsletter"),
            environment={**common_env, "SENDER_EMAIL": sender_email},
            timeout=Duration.seconds(30),
            memory_size=256,
        )
        table.grant_read_write_data(newsletter_fn)
        newsletter_fn.add_to_role_policy(iam.PolicyStatement(
            actions=["ses:SendEmail", "ses:SendRawEmail"],
            resources=["*"],
        ))

        # ------------------------------------------------------------------
        # API Gateway (REST) : Cognito authorizer required for POST /items
        # and POST /subscribe; GET /items and GET /unsubscribe stay public
        # (unsubscribe is a plain link clicked from the email itself).
        # ------------------------------------------------------------------
        api = apigw.RestApi(
            self, "WusomApi",
            rest_api_name=f"wusom-exchange-api-{stage}",
            deploy_options=apigw.StageOptions(stage_name=stage, throttling_rate_limit=20, throttling_burst_limit=10),
            default_cors_preflight_options=apigw.CorsOptions(
                allow_origins=apigw.Cors.ALL_ORIGINS,
                allow_methods=apigw.Cors.ALL_METHODS,
                allow_headers=["Content-Type", "Authorization"],
            ),
        )

        items_integration = apigw.LambdaIntegration(items_fn)
        items_resource = api.root.add_resource("items")
        items_resource.add_method("GET", items_integration)  # public browse
        items_resource.add_method(
            "POST", items_integration,
            authorization_type=apigw.AuthorizationType.COGNITO,
            authorizer=authorizer,
        )

        subscribe_integration = apigw.LambdaIntegration(subscribe_fn)
        subscribe_resource = api.root.add_resource("subscribe")
        subscribe_resource.add_method(
            "POST", subscribe_integration,
            authorization_type=apigw.AuthorizationType.COGNITO,
            authorizer=authorizer,
        )

        unsubscribe_resource = api.root.add_resource("unsubscribe")
        unsubscribe_resource.add_method("GET", subscribe_integration)  # public, token-based

        # ------------------------------------------------------------------
        # EventBridge Scheduler : weekly newsletter trigger
        # ------------------------------------------------------------------
        scheduler_role = iam.Role(
            self, "NewsletterSchedulerRole",
            assumed_by=iam.ServicePrincipal("scheduler.amazonaws.com"),
        )
        newsletter_fn.grant_invoke(scheduler_role)

        scheduler.CfnSchedule(
            self, "WeeklyNewsletterSchedule",
            flexible_time_window=scheduler.CfnSchedule.FlexibleTimeWindowProperty(mode="OFF"),
            schedule_expression="rate(7 days)",
            target=scheduler.CfnSchedule.TargetProperty(
                arn=newsletter_fn.function_arn,
                role_arn=scheduler_role.role_arn,
                input="{}",
            ),
        )

        # ------------------------------------------------------------------
        # S3 static site + CloudFront
        # ------------------------------------------------------------------
        site_bucket = s3.Bucket(
            self, "WusomSiteBucket",
            removal_policy=removal_policy,
            auto_delete_objects=True,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
        )

        distribution = cloudfront.Distribution(
            self, "WusomSiteDistribution",
            default_root_object="index.html",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(site_bucket),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
            ),
        )

        s3deploy.BucketDeployment(
            self, "WusomSiteDeployment",
            sources=[s3deploy.Source.asset("../frontend")],
            destination_bucket=site_bucket,
            distribution=distribution,
            distribution_paths=["/*"],
        )

        # ------------------------------------------------------------------
        # Outputs
        # ------------------------------------------------------------------
        CfnOutput(self, "ApiUrl", value=api.url)
        CfnOutput(self, "SiteUrl", value=f"https://{distribution.distribution_domain_name}")
        CfnOutput(self, "UserPoolId", value=user_pool.user_pool_id)
        CfnOutput(self, "UserPoolClientId", value=user_pool_client.user_pool_client_id)
        CfnOutput(self, "CognitoDomain", value=user_pool_domain.domain_name)
        CfnOutput(self, "TableName", value=table.table_name)
