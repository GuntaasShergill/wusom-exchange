#!/usr/bin/env python3
import os
import aws_cdk as cdk

from stacks.wusom_stack import WusomExchangeStack

app = cdk.App()
stage = app.node.try_get_context("stage") or "dev"

env = cdk.Environment(
    account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
    region=os.environ.get("CDK_DEFAULT_REGION", "us-east-2"),
)

WusomExchangeStack(
    app,
    f"WusomExchange-{stage}",
    stage=stage,
    env=env,
    description="WUSOMExchange: free item exchange marketplace for WashU School of Medicine",
)

app.synth()
