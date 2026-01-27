import requests 
from datetime import datetime
from pydantic import BaseModel
from typing import List

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

class ActionList(BaseModel):
    actions: List[Action]

def view_action(
    user_id: str,
):
    # Construct URL from base URL
    url = f"{base_url}/action"
    header = {
        "user-id": user_id
    }

    # Run request
    try:
        res = requests.get(url, headers=header)
        return res.json()
        # return ActionList(**res.json()).model_dump()
    except Exception as e:
        print(f"Failed to fetch actions. Details: {e}")

# print(view_action('CORZZX0MxTQtGyAD7PSCI1HLp3y2'))