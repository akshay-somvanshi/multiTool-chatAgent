from google.cloud import firestore
from langchain_core.messages import HumanMessage, AIMessage

db = firestore.Client()

# Wrapper for Firestore to be able to store and retrieve messages
class FireStoreChat():  
    def __init__(self, user_id, session_id):
        "We would like the structure: messages/{user_id}/{session_id}/message"
        self.ref = (db.collection("messages")
                    .document(user_id)
                    .collection("sessions")
                    .document(session_id)
                    .collection("messages")
        )

        self.user_ref = (db.collection("users")
                         .document(user_id)
        )

    def add_user_message(self, content):
        self.ref.add({
            "role": "user",
            "content": content,
            "timestamp": firestore.SERVER_TIMESTAMP
        })

    def add_ai_message(self, content):
        self.ref.add({
            "role": "ai",
            "content": content,
            "timestamp": firestore.SERVER_TIMESTAMP
        })

    def load_messages(self):
        list_messages = self.ref.order_by("timestamp").stream()
        data = []
        for message in list_messages:
            msg = message.to_dict()
            if msg["role"] == "user":
                data.append(HumanMessage(content=msg["content"]))
            else:
                data.append(AIMessage(content=msg["content"]))

        return data

    def load_sessions(self, user_id):
        pass

    def get_user_context(self):
        user_data = self.user_ref.get().to_dict()

        if user_data['sustainability_strategy']:
            strat = "they have a sustainability strategy"
        else:
            strat = "they do not have a sustainability strategy"

        if user_data['operate_in_uk']:
            uk_oper = "they operate in the UK"
        else:
            uk_oper = "they do not operate in the UK"

        context = ( 
            f"Here are the initial details about the user. "
            f"Their first name is {user_data.get('first_name', '')}, " 
            f"their last name is {user_data.get('last_name', '')}, " 
            f"their company name is {user_data.get('company_name', '')}, " 
            f"and it is in the {user_data.get('company_industry', '')} industry. " 
            f"They work in the {user_data.get('team', '')} team/department, " 
            f"{uk_oper}, and {strat}." 
        ) 
        
        return context
        