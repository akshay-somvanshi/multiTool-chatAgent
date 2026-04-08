import unittest
from unittest.mock import patch, MagicMock
from fastapi import HTTPException
import asyncio
import sys

# We mock 'firebase_admin' before importing 'get_user_id' because 'get_user_id' 
# imports firebase_admin at the top of its file. This prevents the 
# real Firebase SDK from trying to initialize (which would fail without config).
mock_firebase = MagicMock()
sys.modules['firebase_admin'] = mock_firebase
sys.modules['firebase_admin.auth'] = MagicMock()

# Now we can safely import the function we want to test
from chat_agent.core.auth import get_user_id

class TestAuth(unittest.TestCase):
    
    # @patch replaces the real 'verify_id_token' function with a 'mock_verify' object
    # for the duration of this test method.
    @patch('chat_agent.core.auth.auth.verify_id_token')
    def test_get_user_id_success(self, mock_verify):
        """Test that a valid token returns the correct User ID."""
        
        # Setup: Tell the mock exactly what to return when it's called.
        # This simulates a successful response from Firebase.
        mock_verify.return_value = {"uid": "test_service_user_123"}
        
        # Setup: Create a fake 'credentials' object that FastAPI usually provides.
        res = MagicMock()
        res.credentials = "valid_token"
        
        # Execution: Run the async function using asyncio.run() 
        # since unittest is synchronous.
        uid = asyncio.run(get_user_id(res))
        
        # Assertions: Verify the results are what we expected.
        self.assertEqual(uid, "test_service_user_123")
        
        # Verification: Ensure our code actually called the firebase function 
        # with the correct token string.
        mock_verify.assert_called_once_with("valid_token")

    @patch('chat_agent.core.auth.auth.verify_id_token')
    def test_get_user_id_failure(self, mock_verify):
        """Test that an invalid token raises a 401 HTTPException."""
        
        # Setup: Tell the mock to raise an Exception when called.
        # This simulates Firebase rejecting an expired or fake token.
        mock_verify.side_effect = Exception("Invalid token")
        
        res = MagicMock()
        res.credentials = "invalid_token"
        
        # Execution & Assertion: Wrap the call in 'assertRaises'.
        # This test passes if an HTTPException is thrown.
        with self.assertRaises(HTTPException) as cm:
            asyncio.run(get_user_id(res))
        
        # Validation: Check if the error has the right status code and message.
        self.assertEqual(cm.exception.status_code, 401)
        self.assertIn("Invalid or expired authentication token", cm.exception.detail)

if __name__ == '__main__':
    unittest.main()
