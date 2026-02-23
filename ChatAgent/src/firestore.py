from google.cloud import firestore
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

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

        self.user_id = user_id

    def add_user_message(self, content):
        self.ref.add({
            "role": "user",
            "content": content,
            "timestamp": firestore.SERVER_TIMESTAMP
        })

    def add_system_message(self, content):
        self.ref.add({
            "role": "system",
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
        try:
            list_messages = self.ref.order_by("timestamp").stream()
            data = []
            for message in list_messages:
                msg = message.to_dict()
                content = msg.get("content", "")

                if isinstance(content, list):
                    content = content[0].get("text", "") 

                # Skip empty content
                if not content or not content.strip():
                    continue

                if msg["role"] == "user":
                    data.append(HumanMessage(content=content))
                elif msg["role"] == "system":
                    data.append(SystemMessage(content=content))
                else:
                    data.append(AIMessage(content=content))

            return data
        except Exception as e:
            print(f"Error loading messages: {e}")
            return []

    def load_all_messages(self, current_session_id):
        try:
            session_ref = db.collection("messages").document(self.user_id).collection("sessions")
            sessions = session_ref.list_documents()
            data = []

            for session in sessions:
                # Skip the current session
                if session.id == current_session_id:
                    continue

                # The session object is a CollectionReference, so we use its ID.
                list_messages = (db.collection("messages")
                                .document(self.user_id)
                                .collection("sessions")
                                .document(session.id)
                                .collection("messages")
                                .order_by("timestamp")
                                .stream()
                )
                for message in list_messages:
                    msg = message.to_dict()

                    content = msg.get("content", "")

                    if isinstance(content, list):
                        content = content[0].get("text", "") 

                    # Skip empty content
                    if not content or not content.strip():
                        continue
                    
                    if msg["role"] == "user":
                        data.append(HumanMessage(content=content))
                    else:
                        data.append(AIMessage(content=content))

            return data
        except Exception as e:
            print(f"Error loading messages: {e}")
            return []

    def get_user_context(self):
        try:
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
                f"Their user_id is {self.user_id}" 
            ) 
            
            return context
        except Exception as e:
            print(f"Error loading user context: {e}")
            return ""
        