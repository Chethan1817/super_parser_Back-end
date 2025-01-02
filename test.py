import requests
import time

def test_api_limits():
    api_key = "b4aaf629-f3bf-4632-bd98-af54e1554035"
    url = "http://localhost:9080/api/test/"
    headers = {"X-API-KEY": api_key}
    
    print("Starting API limit test...")
    
    for i in range(2000):  
        response = requests.get(url, headers=headers)
        status_code = response.status_code
        
        print(f"Request {i + 1}: Status Code {status_code}")
        if status_code != 200:
            print(f"Response: {response.text}")
        

if __name__ == "__main__":
    test_api_limits()