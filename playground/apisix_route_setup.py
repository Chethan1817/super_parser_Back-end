import requests
from datetime import datetime

class APISIXSubscriptionManager:
    def __init__(self):
        self.admin_key = "edd1c9f034335f136f87ad84b625c8f1"
        self.base_url = "http://127.0.0.1:9180/apisix/admin"
        self.headers = {
            "X-API-KEY": self.admin_key,
            "Content-Type": "application/json"
        }
        
        self.subscription_configs = {
            "free": {
                "monthly_limit": 50,
                "rate_limit": 2,
                "error_msg": "Free tier limit reached. Please upgrade your subscription."
            },
            "basic": {
                "monthly_limit": 500,
                "rate_limit": 5,
                "error_msg": "Basic tier limit reached. Please upgrade your subscription."
            },
            "advance": {
                "monthly_limit": 2000,
                "rate_limit": 5,
                "error_msg": "Advanced tier limit reached. Please upgrade your subscription."
            },
            "premium": {
                "monthly_limit": 5000,
                "rate_limit": 5,
                "error_msg": "Premium tier limit reached. Contact support for custom plans."
            }
        }

    def create_or_update_consumer(self, email, api_key, subscription_tier="free"):
        valid_username = f"user_{email.replace('@', '_').replace('.', '_')}"
        consumer_url = f"{self.base_url}/consumers/{valid_username}"
        
        try:
            # Delete existing consumer if any
            requests.delete(consumer_url, headers=self.headers)
            
            config = self.subscription_configs.get(subscription_tier, self.subscription_configs["free"])
            
            # Create consumer with plugins
            payload = {
                "username": valid_username,
                "plugins": {
                    "key-auth": {
                        "key": api_key
                    },
                    "limit-count": {
                        "count": config["monthly_limit"],
                        "time_window": 30 * 24 * 3600,
                        "rejected_code": 429,
                        "rejected_msg": config["error_msg"],
                        "key": "consumer_name",
                        "policy": "local",
                        "allow_degradation": False
                    },
                    "limit-req": {
                        "rate": config["rate_limit"],
                        "burst": config["rate_limit"] * 2,
                        "rejected_code": 429,
                        "rejected_msg": "Rate limit exceeded. Please slow down.",
                        "key": "consumer_name",
                        "allow_degradation": False
                    }
                },
                "desc": f"Consumer for {email} - {subscription_tier} tier"
            }
            
            # Create route specifically for /api/test endpoint
            route_payload = {
                "uri": "/api/test/*",  # Changed from "/api/*" to "/api/test/*"
                "plugins": {
                    "key-auth": {},
                    "proxy-rewrite": {
                        "regex_uri": ["^/api/test/(.*)", "/$1"]  # Updated regex to handle /api/test/ path
                    }
                },
                "upstream": {
                    "type": "roundrobin",
                    "nodes": {
                        "127.0.0.1:8001": 1
                    }
                }
            }
            
            # Create new consumer
            response = requests.put(consumer_url, headers=self.headers, json=payload)
            
            if response.status_code not in [200, 201]:
                return False, f"Failed to create/update consumer: {response.text}"
            
            # Create route for this API
            route_url = f"{self.base_url}/routes/api_{valid_username}"
            route_response = requests.put(route_url, headers=self.headers, json=route_payload)
            
            if route_response.status_code not in [200, 201]:
                return False, f"Failed to create/update route: {route_response.text}"
            
            return True, None
            
        except requests.exceptions.RequestException as e:
            return False, str(e)

    def upgrade_subscription(self, email, new_tier):
        valid_username = f"user_{email.replace('@', '_').replace('.', '_')}"
        consumer_url = f"{self.base_url}/consumers/{valid_username}"
        
        try:
            response = requests.get(consumer_url, headers=self.headers)
            if response.status_code != 200:
                return False, "Consumer not found"
            
            consumer_data = response.json()
            api_key = consumer_data['value']['plugins']['key-auth']['key']
            
            return self.create_or_update_consumer(email, api_key, new_tier)
            
        except requests.exceptions.RequestException as e:
            return False, str(e)