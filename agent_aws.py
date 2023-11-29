from base64 import b64decode, b64encode, urlsafe_b64decode
import os
from typing import Any, Dict, List

import boto3
from botocore.exceptions import ClientError
from langchain.agents import AgentType, initialize_agent
from langchain.embeddings import BedrockEmbeddings
from langchain.llms import Bedrock
from langchain.memory import ConversationBufferMemory
from langchain.prompts import MessagesPlaceholder
from langchain.schema.messages import AIMessage, HumanMessage
from langchain.tools import StructuredTool
from langchain.vectorstores import FAISS

import create_lambda_function_helpers as lambda_helpers
import requests, json

# Initialize AWS clients
s3 = boto3.client("s3")
lambda_client = boto3.client("lambda")
profanitycheck_lambda_function_url = "https://qyvrqxyev5iavk2v3v6hfgkwti0petst.lambda-url.us-east-1.on.aws/"
raicheck_lambda_function_url = "https://d670lckjte.execute-api.us-east-1.amazonaws.com/dev/resonponsibleAI"


# Retrieve environment variables
LAMBDA_ROLE = os.environ["LAMBDA_ROLE"]
S3_BUCKET = os.environ["S3_BUCKET"]


def setup_bedrock():
    """Initialize the Bedrock runtime."""
    return boto3.client(
        service_name="bedrock-runtime",
        region_name="us-east-1",
    )


def initialize_llm(client):
    """Initialize the language model."""
    llm = Bedrock(client=client, model_id="anthropic.claude-v2")
    llm.model_kwargs = {"temperature": 0.0, "max_tokens_to_sample": 4096}
    return llm


# Setup bedrock
bedrock_runtime = boto3.client(
    service_name="bedrock-runtime",
    region_name="us-east-1",
)


def well_arch_tool(query: str) -> Dict[str, Any]:
    """Returns text from AWS Well-Architected Framework related to the query."""
    embeddings = BedrockEmbeddings(
        client=bedrock_runtime,
        model_id="amazon.titan-embed-text-v1",
    )
    vectorstore = FAISS.load_local("local_index", embeddings)
    docs = vectorstore.similarity_search(query)
    return {"docs": docs}


def create_lambda_function(
    code: str,
    function_name: str,
    description: str,
    has_external_python_libraries: bool,
    external_python_libraries: List[str],
) -> str:
    """
    Creates a deploys a Lambda Function, based on what the customer requested. Returns the name of the created Lambda function
    """

    print("Creating Lambda function")

    # !!! HARD CODED !!!
    runtime = "python3.9"
    handler = "lambda_function.handler"

    # Create a zip file for the code
    if has_external_python_libraries:
        zipfile = lambda_helpers.create_deployment_package_with_dependencies(
            code, function_name, f"{function_name}.zip", external_python_libraries
        )
    else:
        zipfile = lambda_helpers.create_deployment_package_no_dependencies(
            code, function_name, f"{function_name}.zip"
        )

    try:
        # Upload zip file
        # !!! HARD CODED !!!.
        zip_key = f"agent_aws_resources/{function_name}.zip"
        s3.upload_file(zipfile, S3_BUCKET, zip_key)

        print(f"Uploaded zip to {S3_BUCKET}/{zip_key}")

        response = lambda_client.create_function(
            Code={
                "S3Bucket": S3_BUCKET,
                "S3Key": zip_key,
            },
            Description=description,
            FunctionName=function_name,
            Handler=handler,
            Timeout=30,  # hard coded
            Publish=True,
            Role=LAMBDA_ROLE,
            Runtime=runtime,
        )

        print("done and done")
        print(response)
        deployed_function = response["FunctionName"]

        user_response = f"The function {deployed_function} has been deployed, to the customer's AWS account. I will now provide my final answer to the customer on how to invoke the {deployed_function} function with boto3 and print the result."

        return user_response

    except ClientError as e:
        print(e)
        return f"Error: {e}\n Let me try again..."
    

def profanitycheck_lambda_function(
    req: str,
) -> str:
    """
    Call profanitycheck lambda function to check if the input string contains profanity.
    """

    print("Call profanitycheck lambda function to check if the input string contains profanity")



    try:

        print(req)
        data = {"body":req}
        response = requests.post(profanitycheck_lambda_function_url, data =data, headers = {'Content-Type': 'application/json'})

        print(response)

        user_response = f"response from profanitycheck lambda function is {response.text}"

        return user_response

    except ClientError as e:
        print(e)
        return f"Error: {e}\n Let me try again..."

def raicheck_lambda_function(
    req: str,
) -> str:
    """
    Call responsible AI check lambda function to check if the input string contains PII profanity bias.
    """

    print("Call PII profanity biascheck lambda function to check if the input string contains PII profanity bias")



    try:

        print(req)
        data = {
                "responsibleAi_checklist":"piicheck,profanity,bias",
                "prompt":req
                }
        response = requests.post(raicheck_lambda_function_url, data =data, headers = {'Content-Type': 'application/json', 'x-api-key': 'bd0cIjKDti1Tim4hZoTKJ4bvB42yeQeh8ulTdvqb'})

        print(response)

        user_response = f"response from piicheck,profanity,bias check lambda function is {response.text}"

        return user_response

    except ClientError as e:
        print(e)
        return f"Error: {e}\n Let me try again..."


def interact_with_agent_st(agent_executor, input_query, chat_history, st_callback):
    """Interact with the agent and store chat history. Return the response."""

    result = agent_executor.run(
        {
            "input": input_query,
            "chat_history": chat_history,
        },
        callbacks=[st_callback],
    )
    return result


def interact_with_agent(agent_executor, input_query, chat_history):
    """Interact with the agent and store chat history. Return the response."""
    result = agent_executor.invoke(
        {
            "input": input_query,
            "chat_history": chat_history,
        }
    )
    chat_history.append(HumanMessage(content=input_query))
    chat_history.append(AIMessage(content="Assistant: " + result["output"]))
    return result


def setup_full_agent():
    # Initialize bedrock and llm
    bedrock_runtime = setup_bedrock()
    llm = initialize_llm(bedrock_runtime)

    # Initialize tools
    aws_well_arch_tool = StructuredTool.from_function(well_arch_tool)

    create_lambda_function_tool = StructuredTool.from_function(create_lambda_function)

    profanicty_check_function_tool = StructuredTool.from_function(profanitycheck_lambda_function)
    
    rai_check_function_tool = StructuredTool.from_function(raicheck_lambda_function)

    custom_prefix = """
    You are resonsible AI, your role is check piicheck,profanity,bias responsible AI check first, You are an expert AWS Certified Solutions Architect. Your role is to help customers understand best practices on building on AWS. You will always reference the AWS Well-Architected Framework when customers ask questions on building on AWS. You also are an expert Python developer that can create and deploy Lambda functions to help customers solve their problems. The lambda handler must be named 'handler'. The input data for the Lambda functions will always be sent as JSON in the request body with appropriate keys. To extract input data, you must first parse the "body' field of the event parameter using json.loads(), and then extract the appropriate keys from the parsed JSON. You have expertise in various python libraries and can select the appropriate ones to achieve the desired functionality. If there are any Python dependencies, ensure they are separated by commas. If there is user input data for the Lambda functions, they will always be sent as JSON in the request body with appropriate keys. To extract input data, you must first parse the body field of the event parameter using json.loads(), and then extract the appropriate keys from the parsed JSON. The output will always be a JSON response with the format "statusCode": 200, "body": ...
    """

    custom_suffix = """
    Remember as a responsible AI expert, speak as a respnsible export and use rai_check_function_tool to check PII, profanity, bias and speak as an expert AWS Certified Solutions Architect. If you create a Lambda Function for the customer, explain how they can invoke the function using the lambda invoke from boto3 and if they need any payload to input to the function. If the Lambda function calls other AWS services, remind the customer to check that the Lambda role has access to the service.
    """

    chat_message_int = MessagesPlaceholder(variable_name="chat_history")
    memory = ConversationBufferMemory(memory_key="chat_history", return_messages=True)
    agent_executor = initialize_agent(
        [rai_check_function_tool,aws_well_arch_tool, create_lambda_function_tool,],
        llm,
        agent=AgentType.STRUCTURED_CHAT_ZERO_SHOT_REACT_DESCRIPTION,
        agent_kwargs={
            "prefix": custom_prefix,
            "suffix": custom_suffix,
            "memory_prompts": [chat_message_int],
            "input_variables": ["input", "agent_scratchpad", "chat_history"],
        },
        memory=memory,
        verbose=True,
        handle_parsing_errors=True,
    )

    return agent_executor


def main():
    # Initialize agent
    agent_executor = setup_full_agent()

    # Initialize chat history
    chat_history = []

    # Test the agent with questions
    input1 = "Can you create and deploy lambda function that can generate a random number between 1 and 3000?"
    response1 = interact_with_agent(agent_executor, input1, chat_history)
    print(response1)

    input2 = "What does the AWS Well-Architected Framework say about how to create secure VPCs?"
    response2 = interact_with_agent(agent_executor, input2, chat_history)
    print(response2)

    # Clear chat history
    chat_history = []

    input3 = "Can you create and deploy a Lambda function that performs sentiment analysis on input text?"
    response3 = interact_with_agent(agent_executor, input3, chat_history)
    print(response3)


if __name__ == "__main__":
    main()
