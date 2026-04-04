from mangum import Mangum
from server import app

# Create the Lambda handler
handler = Mangum(app) # Mangum wrapper over the FastAPI app to allow serverless calls from AWS Lambda

# Mangum is a wrapper that allows FastAPI (and other ASGI frameworks) to run on AWS Lambda. It translates API Gateway events into ASGI scope and vice versa, enabling seamless integration between FastAPI and AWS Lambda.
# app is the FastAPI application instance defined in server.py
# handler is the function that AWS Lambda will invoke when the Lambda function is called. It uses Mangum to handle the incoming request and route it to the appropriate endpoint defined in the FastAPI app.