from google.cloud import firestore
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

import time

db = firestore.Client()

# Wrapper for Firestore to be able to store and retrieve messages
class FireStoreChat():  
    def __init__(self, user_id, session_id):
        "We would like the structure: messages/{user_id}/{session_id}/message"
        self.session_doc_ref = (db.collection("messages")
                    .document(user_id)
                    .collection("sessions")
                    .document(session_id)
        )
        self.ref = self.session_doc_ref.collection("messages")

        self.user_ref = (db.collection("users")
                         .document(user_id)
        )

        self.user_id = user_id

    def add_user_message(self, content):
        try:
            self.ref.add({
                "role": "user",
                "content": content,
                "timestamp": firestore.SERVER_TIMESTAMP
            })
        except Exception as e:
            print(f"Error adding user message: {e}")

    def add_system_message(self, content):
        try:
            self.ref.add({
                "role": "system",
                "content": content,
                "timestamp": firestore.SERVER_TIMESTAMP
            })
        except Exception as e:
            print(f"Error adding system message: {e}")

    def add_ai_message(self, content):
        try:
            self.ref.add({
                "role": "ai",
                "content": content,
                "timestamp": firestore.SERVER_TIMESTAMP
            })
        except Exception as e:
            print(f"Error adding AI message: {e}")

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

    def load_session_list(self):
        """List all session document references for this user."""
        try:
            session_ref = db.collection("messages").document(self.user_id).collection("sessions")
            return session_ref.list_documents()
        except Exception as e:
            print(f"Error listing sessions: {e}")
            return []

    def load_messages_by_id(self, session_id):
        """Load messages for a specific session ID."""
        try:
            list_messages = (db.collection("messages")
                             .document(self.user_id)
                             .collection("sessions")
                             .document(session_id)
                             .collection("messages")
                             .order_by("timestamp")
                             .stream()
            )
            data = []
            for message in list_messages:
                msg = message.to_dict()
                content = msg.get("content", "")
                if not content or not content.strip():
                    continue
                
                if msg["role"] == "user":
                    data.append(HumanMessage(content=content))
                else:
                    data.append(AIMessage(content=content))
            return data
        except Exception as e:
            print(f"Error loading session {session_id}: {e}")
            return []

    def load_all_messages(self, current_session_id):
        # Kept for backward compatibility, but we should use the parallel version
        try:
            sessions = self.load_session_list()
            data = []
            for session in sessions:
                if session.id == current_session_id:
                    continue
                data.extend(self.load_messages_by_id(session.id))
            return data
            
        except Exception as e:
            print(f"Error loading messages: {e}")
            return []

    def get_user_context(self):
        start_time = time.perf_counter()
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
            

            print(f"[Profiling] User Context took {time.perf_counter() - start_time:.2f}s")

            return context
        except Exception as e:
            print(f"Error loading user context: {e}")
            return ""

    def set_status(self, status_key):
        """Update the session document with a witty status message."""
        status_map = {
            "classifier": [
                "Deciding how to tackle this...",
                "Selecting the right intelligence mode...",
                "Analyzing your request...",
                "Consulting the internal logic map..."
            ],
            "history": [
                "Recalling our last conversation...",
                "Looking through our chat history...",
                "Remembering context...",
                "Getting up to speed on where we left off..."
            ],
            "summary": [
                "Summarizing previous insights...",
                "Synthesizing your past feedback...",
                "Distilling the key points of our journey...",
                "Connecting the dots across sessions..."
            ],
            "search": [
                "Consulting the digital experts...",
                "Searching the web for the freshest facts...",
                "Scanning the hive mind (Google)...",
                "Deep-diving into online resources..."
            ],
            "agent_thinking": [
                "Formulating the perfect reply...",
                "Crunching the numbers...",
                "Applying some serious processing power...",
                "Thinking through the implications..."
            ],
            "finishing": [
                "Polishing the response...",
                "Almost there...",
                "Wrapping up the insights...",
                "Finalizing the details..."
            ]
        }

        import random
        messages = status_map.get(status_key, ["Processing..."])
        message = random.choice(messages)
        
        try:
            self.session_doc_ref.set({
                "status": message,
                "status_key": status_key,
                "last_status_update": firestore.SERVER_TIMESTAMP
            }, merge=True)
            print(f"[Firestore] Status updated to: {message}")
        except Exception as e:
            print(f"Error updating status: {e}")
        