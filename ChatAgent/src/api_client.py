import requests 
from datetime import datetime
from pydantic import BaseModel
from typing import List
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter

# from ..core.exceptions import APIError
class APIError(Exception):
    def __init__(self, message, error):
        super().__init__(message)
        self.error = error 

base_url = "https://api-app-441601669115.europe-west1.run.app/"

class Action(BaseModel):
    action_id: str
    action_name: str
    action_type: str
    action_description: str
    estimated_spend: float
    estimated_co2_reduced: float
    estimated_revenue_unlocked: float
    plan_id: str
    timeline_start: datetime
    timeline_end: datetime
    status: str
    # created_at: str
    # user_id: str

class ActionList(BaseModel):
    actions: List[Action]

class BaseAPIClient:
    def __init__(self, base_url):
        self.base_url = base_url
        self.session = self._create_session()

    def _create_session(self):
        session = requests.Session()
        retry = Retry(total=3)
        adapter = HTTPAdapter(max_retries=retry)
        session.mount('https://', adapter)
        return session
    
    def _make_request(self, method, endpoint, user_id, **kwargs):
        url = f"{self.base_url}/{endpoint}"
        headers = {"user-id" : user_id}

        try: 
            res = self.session.request(method, url, headers=headers, timeout=10, **kwargs)
            # Raises HTTP error if occurs
            res.raise_for_status()
            return res.json()
        except requests.Timeout:
            raise APIError("Request timed out", None)
        except Exception as e:
            raise APIError(f"Failed to {method} {endpoint}", e)

    def view_actionList(
        self,
        user_id: str,
    ):
        data = self._make_request(method="GET", endpoint="action", user_id=user_id)
        if isinstance(data,list):
            # Wrap list into Action type
            action_data = [Action(**item).model_dump() for item in data]
            return {"actions" : action_data}
        return ActionList(**data).model_dump()

    # def view_action(
    #     self,
    #     user_id: str,
    #     action_id: str
    # ):
    #     return Action()

    def add_action(
        user_id: str,
        payload: Action
    ):
        pass

base = BaseAPIClient(base_url)
print(base.view_actionList('CORZZX0MxTQtGyAD7PSCI1HLp3y2'))