# agentgo_mcp_service.py
import os
from fastmcp import FastMCP
import asyncio
from loguru import logger
import aiohttp
from typing import Optional, Dict, Any, Union
from datetime import datetime
import json
import random
import hashlib
from eth_account.messages import encode_defunct
from eth_account import Account
import secrets

# API Configuration
URL_PREFIX = 'https://host-server-web-frat-server-uvoggbicsv.ap-southeast-1.fcapp.run'
TRUSTGO_API_URL = 'https://dev.mp.trustalabs.ai'

mcp = FastMCP(
    name="AgentGo MCP Service", 
    description="""
AgentGo Complete API Service - Agent Authentication, Score Query and Data Analysis

Features:
1. Agent login and X account binding
2. Agent claim sigma attestation
3. Sigma score query
4. Claim sigma attestation for other agents
5. Price bubble information query
6. Sigma score bubble information query
7. Mindshare bubble information query

Usage:
- Set environment variable AGENT_ADDRESS for automatic login
- All authenticated operations require calling login or bind_x_account first
"""
)

# Token storage with user addresses
auth_tokens = {}
user_bindings = {}  # Store X account bindings
agent_challenges = {}  # Store pending challenges for agent verification

# Get user address from environment variable
DEFAULT_ADDRESS = os.getenv('AGENT_ADDRESS', '')
RAPIDAPI_KEY = os.getenv('RAPIDAPI_KEY', '')

# Challenge storage for each address
challenge_storage = {}

async def get_auth_token(access_key: str, secret_access_key: str) -> str:
    """Get API authentication token"""
    url = f'{URL_PREFIX}/service/openapi/getToken'
    headers = {'Content-Type': 'application/json; charset=utf-8'}
    data = {
        "secretAccessKey": secret_access_key,
        "accessKey": access_key
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=data) as response:
            response_data = await response.json()
            if response_data.get('code') == 0:
                authorization_token = response_data['data']['authorizationToken']
                bearer_token = authorization_token.split("Bearer ")[1]
                return bearer_token
            else:
                raise Exception(f"Failed to get token: {response_data.get('message', 'Unknown error')}")

async def query_agent_score(slug: str, token: str) -> Dict[str, Any]:
    """Query agent's sigma score"""
    url = f"{URL_PREFIX}/service/openapi/queryAgentGoScore?slug={slug}"
    headers = {
        "accept": "application/json",
        "Authorization": f"Bearer {token}"
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as response:
            response_data = await response.json()
            if response_data.get('code') == 0:
                return response_data['data']
            else:
                raise Exception(f"Query failed: {response_data.get('message', 'Unknown error')}")

@mcp.tool(name="trustgo_login", description="Using EIP-191 protocol to login to TrustGo with EVM signature")
async def trustgo_login(
    address: str, 
    signature: str,
    message: str,
    invite_code: Optional[str] = "8ZRT9G1",
    invite_from: Optional[str] = "twitter",
    number: Optional[Union[float, int]] = None
) -> dict:
    """
    Login to TrustGo platform with EVM signature,Need to calculate the number first.
    
    Args:
        address: EVM address
        signature: Signature of the login message
        message: Message to sign
        invite_code: Invitation code (default: 8ZRT9G1)
        invite_from: Invitation source (default: twitter)
        number: The calculated number from the challenge
        
    Returns:

        if status is success, dict: Login result with token
        if status is error, dict: Login result with error message and error details
    """
    try:
        # Check if we have a challenge stored for this address
        if address not in challenge_storage:
            return {
                "status": "error",
                "message": "No challenge found for this address. Please call get_trustgo_login_message first"
            }
        
        challenge = challenge_storage[address]
        
        # Verify the message matches
        if message != challenge["message"]:
            return {
                "status": "error",
                "message": "Message does not match the challenge. Please use the message from get_trustgo_login_message",
            }
        
        # Verify the calculated number
        if number is None:
            return {
                "status": "error",
                "message": "Please provide the calculated number from the challenge"
            }
        logger.info(f"--number: {challenge['expected_answer']}")
        
        if number != challenge["expected_answer"]:
            logger.warning(f"Invalid calculation for {address}: expected {challenge['expected_answer']}, got {number}")
            return {
                "status": "error",
                "message": f"Incorrect calculation. Expected: {challenge['expected_answer']}, Got: {number}"
            }
        
        # Clear the challenge after successful verification
        del challenge_storage[address]

        
        url = f"{TRUSTGO_API_URL}/accounts/check_signed_message"
        headers = {
            'accept': 'application/json',
            'Content-Type': 'application/json'
        }
        
        data = {
            "address": address,
            "message": message,
            "mode": "evm",
            "signature": signature,
            "invite_from": {
                "code": invite_code,
                "from": invite_from
            }
        }
        logger.info(f"TrustGo login data: {data}")
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=data) as response:
                response_data = await response.json()
                
                if response.status == 200 and response_data.get('success'):
                    # Extract token from response
                    token = response_data.get('data', {}).get('token', '')
                    if not token:
                        return {
                            "status": "error",
                            "message": "Login failed: No token The signature is incorrect",
                            "address": address,
                            "signature": signature,
                        }
                    
                    # Store the TrustGo token
                    if address not in auth_tokens:
                        auth_tokens[address] = {}
                    auth_tokens[address]['trustgo_token'] = token
                    auth_tokens[address]['trustgo_login_time'] = datetime.now().isoformat()
                    logger.info(f"TrustGo login successful: {address} {token} response: {response_data}")
                    
                    return {
                        "status": "success",
                        "message": "TrustGo login successful",
                        "address": address,
                        "token": token,
                        "login_message": message
                    }
                else:
                    return {
                        "status": "error",
                        "message": f"TrustGo login failed: {response_data.get('message', 'Unknown error')}"
                    }
                    
    except Exception as e:
        return {
            "status": "error",
            "message": f"TrustGo login failed: {str(e)}"
        }

@mcp.tool(name="get_trustgo_login_message", description="Get the message to sign for TrustGo login")
async def get_trustgo_login_message(address: Optional[str] = None) -> dict:
    """
    Get the current login message for TrustGo with a calculation challenge.
    
    Args:
        address: User address (optional, uses DEFAULT_ADDRESS if not provided)
    
    Returns:
        dict: Message to sign and calculation challenge
    """
    user_address = address or DEFAULT_ADDRESS
    if not user_address:
        return {
            "status": "error",
            "message": "Please provide address or set AGENT_ADDRESS environment variable"
        }
    
    timestamp = int(datetime.now().timestamp())
    message = f"sign the message to login trustgo{timestamp}"
    
    # Generate random numbers for the calculation challenge
    num1 = random.randint(1000000, 9999999)
    num2 = random.randint(1000000, 9999999)
    num3 = random.randint(100, 999)
    
    # Create a complex calculation
    expected_answer = (num1 * num2) + (num3 ** 2) - (num1 % num3)
    
    # Store the challenge for this address
    challenge_storage[user_address] = {
        "expected_answer": expected_answer,
        "timestamp": timestamp,
        "message": message,
        "challenge_created": datetime.now().isoformat()
    }
    
    logger.info(f"Created challenge for {user_address}: answer={expected_answer}")
    
    return {
        "status": "success",
        "message": message,
        "calculation_challenge": {
            "description": "Calculate: (num1 * num2) + (num3^2) - (num1 % num3)",
            "num1": num1,
            "num2": num2,
            "num3": num3,
            "formula": f"{num1} * {num2} + {num3}^2 - ({num1} % {num3})"
        },
        "instructions": "Please calculate the result and provide it in the 'number' parameter when calling trustgo_login"
    }

@mcp.tool(name="query_ranked_bubbles", description="Query ranked bubbles data from TrustGo")
async def query_ranked_bubbles(
    bubble_type: str = "price",
    address: Optional[str] = None
) -> dict:
    """
    Query ranked bubbles data
    
    Args:
        bubble_type: Type of bubble data ('price', 'sigma_score', 'mindshare')
        address: User address for authentication (optional)
        
    Returns:
        dict: Ranked bubbles data
    """
    try:
        # Get address
        query_address = address or DEFAULT_ADDRESS
        
        # Check if user has TrustGo token
        trustgo_token = None
        if query_address and query_address in auth_tokens:
            trustgo_token = auth_tokens[query_address].get('trustgo_token')
        
        if not trustgo_token:
            return {
                "status": "error",
                "message": "Please login to TrustGo first using trustgo_login"
            }
        
        # Map bubble types
        type_mapping = {
            "price": "price",
            "sigma_score": "sigma_score",
            "mindshare": "mindshare"
        }
        
        if bubble_type not in type_mapping:
            return {
                "status": "error",
                "message": f"Invalid bubble type. Must be one of: {', '.join(type_mapping.keys())}"
            }
        
        url = f"{TRUSTGO_API_URL}/agentgo/ranked_bubbles"
        headers = {
            'accept': 'application/json',
            'Authorization': f'TOKEN {trustgo_token}'
        }
        params = {
            'type': type_mapping[bubble_type]
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, params=params) as response:
                response_data = await response.json()
                
                if response.status == 200:
                    return {
                        "status": "success",
                        "bubble_type": bubble_type,
                        "data": response_data,
                        "timestamp": datetime.now().isoformat()
                    }
                else:
                    return {
                        "status": "error",
                        "message": f"Failed to query ranked bubbles: {response_data.get('message', 'Unknown error')}"
                    }
                    
    except Exception as e:
        return {
            "status": "error",
            "message": f"Query failed: {str(e)}"
        }


@mcp.tool(name="claim_sigma_attestation", description="Claim sigma attestation")
async def claim_sigma_attestation(token, slug, address: Optional[str] = None) -> dict:
    """
    Agent claims sigma attestation for themselves
    
    Args:
        token: TrustGo token from trustgo_login
        slug: Agent slug with want to claim
        address: Agent address (optional)
        
    Returns:
        dict: Transaction data requiring user signature with following structure:
            {
                "code": 0,
                "message": "request success",
                "data": {
                    "calldata": {
                        "chainId": int,      # 链ID (e.g., 11155111 for Sepolia)
                        "from": str,         # 发送方地址
                        "to": str,           # 合约地址
                        "value": int,        # 交易金额 (wei)
                        "data": str          # 编码后的合约调用数据
                    },
                    "message": {
                        "chain_id": int,     # 目标链ID
                        "address": str,      # 声明地址
                        "score": {
                            "slug": str,     # Agent标识
                            "x": str,        # Twitter handle
                            "eoa": str,      # EOA地址
                            "score": str     # 评分值
                        },
                        "attest_type": str,  # 认证类型 (e.g., "sigma")
                        "period": int,       # 有效期（天）
                        "source": str|null,  # 来源
                        "fee": float         # 手续费
                    }
                },
                "datetime": str|null,
                "success": bool
            }
            
    Note: 
        - The returned calldata needs to be signed and sent as a transaction
        - The 'data' field contains the encoded contract method call
        - The transaction requires a small fee (value field in wei)
    """
    try:
        url = f"{TRUSTGO_API_URL}/accounts/attest_calldata?attest_type=sigma&slug={slug}"
        headers = {
            'accept': 'application/json',
            'Authorization': f'TOKEN {token}'
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                response_data = await response.json()
                if response_data.get('code') == 0:
                    return {
                        "status": "success",
                        "message": "Sigma attestation claimed successfully",
                        "data": response_data.get('data', {})
                    }
                else:
                    return {
                        "status": "error",
                        "message": f"Failed to claim sigma attestation: {response_data.get('message', 'Unknown error')}"
                    }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Claim failed: {str(e)}"
        }


@mcp.tool(name="query_price_bubble_info", description="Query price bubble information")
async def query_price_bubble_info(agent_slug: Optional[str] = None, address: Optional[str] = None) -> dict:
    """
    Query price bubble information
    
    Args:
        agent_slug: Agent identifier (optional, queries overall market if not provided)
        address: User address for authentication (optional)
        
    Returns:
        dict: Price bubble data
    """
    try:
        # Use the ranked_bubbles API
        result = await query_ranked_bubbles(bubble_type="price", address=address)
        
        if result["status"] == "success":
            # Transform the data to match expected format
            data = result.get("data", {})
            return {
                "status": "success",
                "query_target": agent_slug or "Overall Market",
                "price_bubble_data": data,
                "update_time": result.get("timestamp", datetime.now().isoformat())
            }
        else:
            return result
            
    except Exception as e:
        return {
            "status": "error",
            "message": f"Query failed: {str(e)}"
        }
@mcp.tool(name="verify_twitter_signature", description="verify the signature of the message")
async def verify_twitter_signature(tweet_id: str,  address: Optional[str] = None) -> dict:
    """
    Verify the signature of the message
    Args:
        tweet_id: The id of the tweet
        address: The address of the user
    Returns:
        dict: The result of the verification if success, the slug will be in the data
    """
    try:
        url = f"https://twitter-api45.p.rapidapi.com/tweet.php"
        querystring = {"id":tweet_id}


        headers = {
            "x-rapidapi-key": RAPIDAPI_KEY,
            "x-rapidapi-host": "twitter-api45.p.rapidapi.com"
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, params=querystring) as response:
                response_data = await response.json()
                if response_data.get("text") != challenge_storage[address]["twitter"]["message"]:
                    return {
                        "status": "error",
                        "message": "Twitter signature verification failed",
                        "data": response_data,
                        "error": "The message is not the same as the one generated by the tool"
                    }
                user_screen_name = response_data.get("author").get("screen_name")
                challenge_storage[address]["twitter"]["user_screen_name"] = user_screen_name

                return {
                    "status": "success",
                    "message": "Twitter signature verified successfully",
                    "data": response_data,
                    "user_screen_name": user_screen_name
                }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Sign failed: {str(e)}"
        }

@mcp.tool(name="login_twitter", description="generate a message to login with twitter")
async def login_twitter( address: Optional[str] = None) -> dict:
    """
    if Need to sign with twitter, you can use this tool to generate a message to sign with twitter
    Using need send a tweet with the message to the twitter account, and then use the signature to login to AgentGo
    """
    number = random.randint(1000000, 9999999)
    message = f"Using AgentGo to sign with twitter {address} code is {number}"
    if address not in challenge_storage:
        challenge_storage[address] = {"twitter":{
            "message": message,
            "number": number,
        }}
    else:
        challenge_storage[address]["twitter"] = {
            "message": message,
            "number": number,
        }


    try:
        return {
            "status": "success",
            "message": message,
            "number": number
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Sign failed: {str(e)}"
        }

@mcp.tool(name="query_sigma_score_bubble_info", description="Query sigma score bubble information")
async def query_sigma_score_bubble_info(category: Optional[str] = None, address: Optional[str] = None) -> dict:
    """
    Query sigma score bubble information
    
    Args:
        category: Category (optional, e.g., 'defi', 'gaming', 'social')
        address: User address for authentication (optional)
        
    Returns:
        dict: Sigma score bubble data
    """
    try:
        # Use the ranked_bubbles API
        result = await query_ranked_bubbles(bubble_type="sigma_score", address=address)
        
        if result["status"] == "success":
            # Transform the data to match expected format
            data = result.get("data", {})
            return {
                "status": "success",
                "category": category or "All",
                "sigma_bubble_data": data,
                "update_time": result.get("timestamp", datetime.now().isoformat())
            }
        else:
            return result
            
    except Exception as e:
        return {
            "status": "error",
            "message": f"Query failed: {str(e)}"
        }


if __name__ == "__main__":
    # Auto login if environment variable is set
    if DEFAULT_ADDRESS:
        print(f"Detected AGENT_ADDRESS environment variable: {DEFAULT_ADDRESS}")
        print("Will auto login after service starts...")
    
    mcp.run()