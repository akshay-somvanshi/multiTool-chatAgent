import requests 
from datetime import datetime
from pydantic import BaseModel
from typing import List
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter

from chat_agent.core.exceptions import APIError

base_url = "https://api-app-441601669115.europe-west1.run.app/"

class Action(BaseModel):
    action_id: str
    action_name: str
    action_type: str
    action_description: str
    estimated_spend: float
    estimated_co2_reduced: float
    estimated_revenue_unlocked: float
    actual_co2_reduced: float | None
    actual_spend: float | None
    actual_revenue_unlocked: float | None
    actual_time_taken: float | None
    plan_id: str
    timeline_start: datetime
    timeline_end: datetime
    status: str

class ActionList(BaseModel):
    actions: List[Action]

class updateActionPayload(BaseModel):
    actual_co2_reduced: float | None
    actual_spend: float | None
    actual_revenue_unlocked: float | None
    day_started: datetime | None
    day_completed: datetime | None

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
            raise APIError("API request timed out", status_code=408)
        except requests.exceptions.HTTPError as e:
            raise APIError(f"API request failed with status {e.response.status_code}: {e.response.text}", status_code=e.response.status_code)
        except Exception as e:
            raise APIError(f"An unexpected error occurred during API request to {endpoint}: {e}")

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

    def add_action_service(
        self,
        user_id: str,
        payload: Action
    ):
        return self._make_request(method="POST", endpoint="action", user_id=user_id, json=payload)
    
    def remove_action_service(
        self,
        user_id: str,
        action_id: str
    ):
        return self._make_request(method="DELETE", endpoint=f"action/{action_id}", user_id=user_id)
    
    def update_action_service(
        self,
        user_id: str,
        action_id: str,
        payload: updateActionPayload
    ):
        return self._make_request(method="PUT", endpoint=f"action/{action_id}", user_id=user_id, json=payload)

api_client = BaseAPIClient(base_url)