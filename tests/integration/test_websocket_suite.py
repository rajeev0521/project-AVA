import asyncio
import websockets
import json
import time

USER_ID = "115473709558120606390"  # The user's ID from the server logs
WS_URL = f"ws://127.0.0.1:8000/ws/{USER_ID}"

TEST_SUITE = {
    "Level 1: Basic Wake Word & Conversation": [
        "Hey Ava",
        "Hey Ava, are you there?",
        "Hey Ava, what can you do?",
        "Hey Ava, what's today's date?",
        "Hey Ava, what time is it?"
    ],
    "Level 2: Simple Reminder Creation": [
        "Hey Ava, remind me to drink water at 5 PM.",
        "Hey Ava, remind me to submit my assignment tomorrow.",
        "Hey Ava, set a reminder for my internship meeting at 10 AM.",
        "Hey Ava, what reminders do I have?",
        "Hey Ava, show today's reminders."
    ],
    "Level 3: Basic Calendar Event Creation": [
        "Hey Ava, schedule a meeting tomorrow at 2 PM.",
        "Hey Ava, create an event called Project Discussion on Friday at 4 PM.",
        "Hey Ava, add a gym session every day at 6 PM.",
        "Hey Ava, what events do I have tomorrow?",
        "Hey Ava, what's on my calendar this week?"
    ],
    "Level 4: Event Modification": [
        "Hey Ava, move my Project Discussion meeting to 5 PM.",
        "Hey Ava, rename my gym session to Workout.",
        "Hey Ava, delete the Project Discussion event.",
        "Hey Ava, show my upcoming events."
    ],
    "Level 5: Conflict Detection": [
        "Hey Ava, schedule Meeting A tomorrow at 3 PM.",
        "Hey Ava, schedule Meeting B tomorrow at 3 PM.",
        "Hey Ava, find the next available slot for Meeting B."
    ],
    "Level 6: Natural Language Understanding": [
        "Hey Ava, book a meeting with my team next Monday afternoon.",
        "Hey Ava, schedule a call with Rahul sometime after lunch.",
        "Hey Ava, set up a study session for two hours this evening."
    ],
    "Level 7: Querying & Search": [
        "Hey Ava, when is my next meeting?",
        "Hey Ava, do I have anything scheduled on Saturday?",
        "Hey Ava, how many meetings do I have this week?",
        "Hey Ava, what is my busiest day this month?"
    ],
    "Level 8: Intelligent Scheduling": [
        "Hey Ava, schedule a 1-hour study session in my free time today.",
        "Hey Ava, find a slot for a team meeting when I'm available.",
        "Hey Ava, suggest the best time for my gym session."
    ],
    "Level 9: Recurring Events": [
        "Hey Ava, schedule a daily standup at 9 AM.",
        "Hey Ava, schedule a weekly review every Friday.",
        "Hey Ava, cancel all future standups."
    ],
    "Level 10: Context Awareness": [
        "Hey Ava, schedule a meeting tomorrow at 2 PM.",
        "Move it to 4 PM.",
        "Rename it to Client Meeting.",
        "Cancel it."
    ],
    "Level 11: Edge Cases": [
        "Hey Ava, schedule a meeting on February 30th.",
        "Hey Ava, create an event at 25 PM.",
        "Hey Ava, schedule two events at the same time.",
        "Hey Ava, delete an event that doesn't exist."
    ],
    "Level 12: Stress Testing": [
        "Hey Ava, create 5 meetings for next week.", # Reduced from 20 to avoid calendar spam
        "Hey Ava, list all events for the next 30 days.",
        "Hey Ava, reschedule every meeting on Monday to Tuesday."
    ],
    "Level 13: Jarvis-Style Assistant Features": [
        "Hey Ava, I have an exam next week. Help me plan my study schedule.",
        "Hey Ava, I have three meetings tomorrow. Suggest breaks between them.",
        "Hey Ava, am I overbooked this week?",
        "Hey Ava, optimize my schedule for maximum focus time."
    ]
}

async def run_tests():
    report = "# Ava Test Execution Report\n\n"
    
    try:
        async with websockets.connect(WS_URL) as ws:
            for level, commands in TEST_SUITE.items():
                print(f"Running {level}...")
                report += f"## {level}\n\n"
                
                for cmd in commands:
                    print(f"  -> {cmd}")
                    
                    # Send command
                    payload = {
                        "text": cmd,
                        "user_name": "TestUser"
                    }
                    await ws.send(json.dumps(payload))
                    
                    # Wait for response
                    # A typical response has "type": "response" and "text"
                    response_text = ""
                    try:
                        resp_str = await asyncio.wait_for(ws.recv(), timeout=20.0)
                        resp_data = json.loads(resp_str)
                        response_text = resp_data.get("text", str(resp_data))
                    except asyncio.TimeoutError:
                        response_text = "[TIMEOUT]"
                    except Exception as e:
                        response_text = f"[ERROR] {str(e)}"
                        
                    print(f"  <- {response_text}\n")
                    
                    report += f"**User:** `{cmd}`\n\n"
                    report += f"**Ava:** {response_text}\n\n"
                    report += "---\n\n"
                    
                    # Small delay between commands to avoid rate limiting
                    await asyncio.sleep(2)
                    
        with open("C:/Users/rajee/.gemini/antigravity-ide/brain/6a36b59d-8846-496e-b86f-63b9858686d9/test_report.md", "w") as f:
            f.write(report)
            
        print("Tests completed. Report saved.")
            
    except Exception as e:
        print(f"Connection failed: {e}")

if __name__ == "__main__":
    asyncio.run(run_tests())
