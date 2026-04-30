#!/usr/bin/env python3
"""
Test Bot Locking Functionality

This script tests the bot locking feature to ensure database consistency
by preventing bot changes mid-conversation.

Usage:
    python tests/test_bot_locking.py
    
Requirements:
    - PyPoe web server running on localhost:8000
    - Valid authentication credentials (if enabled)
"""

import asyncio
import json
import requests
import websockets
from typing import Dict, Any

# Configuration
BASE_URL = "http://localhost:8000"
WS_URL = "ws://localhost:8000"
USERNAME = "sdl2"  # Set if authentication is enabled
PASSWORD = "accelerate"  # Set if authentication is enabled

class BotLockingTester:
    def __init__(self):
        self.session = requests.Session()
        if USERNAME and PASSWORD:
            self.session.auth = (USERNAME, PASSWORD)
    
    def test_rest_api_bot_locking(self) -> Dict[str, Any]:
        """Test bot locking via REST API"""
        print("🧪 Testing REST API bot locking...")
        
        # Step 1: Create a new conversation
        try:
            create_response = self.session.post(f"{BASE_URL}/api/conversation/new", json={
                "title": "Bot Locking Test",
                "bot_name": "Claude-Sonnet-4.6"
            })
            if create_response.status_code != 200:
                return {"status": "fail", "error": f"Failed to create conversation: {create_response.status_code}"}
            
            conversation_id = create_response.json().get("conversation_id")
            print(f"✅ Created conversation: {conversation_id}")
            
            # Step 2: Send first message with original bot
            first_message_response = self.session.post(
                f"{BASE_URL}/api/conversation/{conversation_id}/send",
                json={"message": "Hello, this is a test message", "bot_name": "Claude-Sonnet-4.6"}
            )
            if first_message_response.status_code != 200:
                return {"status": "fail", "error": f"Failed to send first message: {first_message_response.status_code}"}
            
            print("✅ Sent first message with Claude-Sonnet-4.6")
            
            # Step 3: Try to send second message with different bot (should fail)
            second_message_response = self.session.post(
                f"{BASE_URL}/api/conversation/{conversation_id}/send",
                json={"message": "This should fail", "bot_name": "GPT-5.5"}
            )
            
            if second_message_response.status_code == 400:
                error_detail = second_message_response.json().get("detail", "")
                if "Cannot change bot mid-conversation" in error_detail:
                    print("✅ Bot locking correctly prevented bot change")
                    return {
                        "status": "pass",
                        "conversation_id": conversation_id,
                        "locked_to": "Claude-Sonnet-4.6",
                        "attempted_change_to": "GPT-5.5",
                        "error_message": error_detail
                    }
                else:
                    return {"status": "fail", "error": f"Unexpected error message: {error_detail}"}
            else:
                return {"status": "fail", "error": f"Bot change was allowed (status: {second_message_response.status_code})"}
                
        except Exception as e:
            return {"status": "fail", "error": f"Exception: {str(e)}"}
    
    async def test_websocket_bot_locking(self) -> Dict[str, Any]:
        """Test bot locking via WebSocket"""
        print("🧪 Testing WebSocket bot locking...")
        
        # Step 1: Create a new conversation via REST API
        try:
            create_response = self.session.post(f"{BASE_URL}/api/conversation/new", json={
                "title": "WebSocket Bot Locking Test",
                "bot_name": "Gemini-3-Flash"
            })
            if create_response.status_code != 200:
                return {"status": "fail", "error": f"Failed to create conversation: {create_response.status_code}"}
            
            conversation_id = create_response.json().get("conversation_id")
            print(f"✅ Created conversation: {conversation_id}")
            
            # Step 2: Connect to WebSocket and send first message
            ws_url = f"{WS_URL}/ws/chat/{conversation_id}"
            
            # Add authentication header if needed
            headers = {}
            if USERNAME and PASSWORD:
                import base64
                credentials = base64.b64encode(f"{USERNAME}:{PASSWORD}".encode()).decode()
                headers["Authorization"] = f"Basic {credentials}"
            
            async with websockets.connect(ws_url, extra_headers=headers) as websocket:
                # Send first message with original bot
                first_message = {
                    "message": "Hello via WebSocket",
                    "bot_name": "Gemini-3-Flash"
                }
                await websocket.send(json.dumps(first_message))
                
                # Wait for responses
                response_count = 0
                while response_count < 5:  # Wait for user_message, bot_response_start, chunks, bot_response_end
                    try:
                        response = await asyncio.wait_for(websocket.recv(), timeout=10)
                        data = json.loads(response)
                        if data.get("type") == "bot_response_end":
                            break
                        response_count += 1
                    except asyncio.TimeoutError:
                        break
                
                print("✅ Sent first message via WebSocket with Gemini-3-Flash")
                
                # Step 3: Try to send second message with different bot (should fail)
                second_message = {
                    "message": "This should fail via WebSocket",
                    "bot_name": "GPT-5.5"
                }
                await websocket.send(json.dumps(second_message))
                
                # Wait for error response
                try:
                    error_response = await asyncio.wait_for(websocket.recv(), timeout=5)
                    error_data = json.loads(error_response)
                    
                    if error_data.get("type") == "error" and "Cannot change bot mid-conversation" in error_data.get("content", ""):
                        print("✅ WebSocket bot locking correctly prevented bot change")
                        return {
                            "status": "pass",
                            "conversation_id": conversation_id,
                            "locked_to": "Gemini-3-Flash",
                            "attempted_change_to": "GPT-5.5",
                            "error_message": error_data.get("content")
                        }
                    else:
                        return {"status": "fail", "error": f"Unexpected response: {error_data}"}
                        
                except asyncio.TimeoutError:
                    return {"status": "fail", "error": "No error response received from WebSocket"}
                
        except Exception as e:
            return {"status": "fail", "error": f"Exception: {str(e)}"}
    
    def test_new_conversation_bot_selection(self) -> Dict[str, Any]:
        """Test that new conversations allow bot selection"""
        print("🧪 Testing new conversation bot selection...")
        
        try:
            # Create conversation with one bot
            create_response = self.session.post(f"{BASE_URL}/api/conversation/new", json={
                "title": "New Conversation Test",
                "bot_name": "GPT-4-Turbo"
            })
            if create_response.status_code != 200:
                return {"status": "fail", "error": f"Failed to create conversation: {create_response.status_code}"}
            
            conversation_id = create_response.json().get("conversation_id")
            print(f"✅ Created conversation with GPT-4-Turbo: {conversation_id}")
            
            # Send first message (this should work since conversation has no messages yet)
            first_message_response = self.session.post(
                f"{BASE_URL}/api/conversation/{conversation_id}/send",
                json={"message": "First message", "bot_name": "Claude-Sonnet-4.6"}
            )
            
            if first_message_response.status_code == 200:
                print("✅ New conversation correctly allowed bot selection")
                return {
                    "status": "pass",
                    "conversation_id": conversation_id,
                    "original_bot": "GPT-4-Turbo",
                    "selected_bot": "Claude-Sonnet-4.6"
                }
            else:
                return {"status": "fail", "error": f"New conversation bot selection failed: {first_message_response.status_code}"}
                
        except Exception as e:
            return {"status": "fail", "error": f"Exception: {str(e)}"}
    
    def cleanup_test_conversations(self, conversation_ids: list):
        """Clean up test conversations"""
        print("🧹 Cleaning up test conversations...")
        for conv_id in conversation_ids:
            try:
                delete_response = self.session.delete(f"{BASE_URL}/api/conversation/{conv_id}")
                if delete_response.status_code == 200:
                    print(f"✅ Deleted conversation {conv_id}")
                else:
                    print(f"⚠️  Failed to delete conversation {conv_id}")
            except Exception as e:
                print(f"⚠️  Error deleting conversation {conv_id}: {e}")

async def main():
    """Run all bot locking tests"""
    print("🚀 PyPoe Bot Locking Test Suite")
    print("=" * 50)
    
    tester = BotLockingTester()
    test_conversations = []
    
    # Test 1: REST API bot locking
    rest_result = tester.test_rest_api_bot_locking()
    if rest_result.get("conversation_id"):
        test_conversations.append(rest_result["conversation_id"])
    
    # Test 2: WebSocket bot locking
    ws_result = await tester.test_websocket_bot_locking()
    if ws_result.get("conversation_id"):
        test_conversations.append(ws_result["conversation_id"])
    
    # Test 3: New conversation bot selection
    new_conv_result = tester.test_new_conversation_bot_selection()
    if new_conv_result.get("conversation_id"):
        test_conversations.append(new_conv_result["conversation_id"])
    
    # Print results
    print("\n📊 Test Results:")
    print("=" * 50)
    print(f"REST API Bot Locking: {'✅ PASS' if rest_result['status'] == 'pass' else '❌ FAIL'}")
    if rest_result["status"] == "fail":
        print(f"   Error: {rest_result.get('error')}")
    
    print(f"WebSocket Bot Locking: {'✅ PASS' if ws_result['status'] == 'pass' else '❌ FAIL'}")
    if ws_result["status"] == "fail":
        print(f"   Error: {ws_result.get('error')}")
    
    print(f"New Conversation Bot Selection: {'✅ PASS' if new_conv_result['status'] == 'pass' else '❌ FAIL'}")
    if new_conv_result["status"] == "fail":
        print(f"   Error: {new_conv_result.get('error')}")
    
    # Cleanup
    tester.cleanup_test_conversations(test_conversations)
    
    # Summary
    total_tests = 3
    passed_tests = sum(1 for result in [rest_result, ws_result, new_conv_result] if result["status"] == "pass")
    
    print(f"\n🎯 Test Summary: {passed_tests}/{total_tests} tests passed")
    
    if passed_tests == total_tests:
        print("🎉 All tests passed! Bot locking is working correctly.")
        return 0
    else:
        print("⚠️  Some tests failed. Check the PyPoe server logs for details.")
        return 1

if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        exit(exit_code)
    except KeyboardInterrupt:
        print("\n👋 Test cancelled by user")
        exit(1)
    except Exception as e:
        print(f"❌ Test suite failed: {e}")
        exit(1) 