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

    def load_messages(self, user_id):
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