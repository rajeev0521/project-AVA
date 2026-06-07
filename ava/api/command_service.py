from pydantic import BaseModel
from typing import Optional
from ava.brain.assistant_brain import AssistantBrain, AssistantResponse
from ava.conversation.state_manager import UserSession
from ava.brain.tool_router import ToolRouter

class CommandResponseModel(BaseModel):
    text: str
    action_taken: Optional[str] = None
    requires_followup: bool = False

class CommandService:
    def __init__(self, tool_router: ToolRouter):
        self.brain = AssistantBrain(tool_router)

    async def process_command(self, text: str, user_name: str, timezone_str: str, session: UserSession) -> CommandResponseModel:
        # Pass the query to AssistantBrain
        response = await self.brain.process(text, session)
        return CommandResponseModel(
            text=response.text,
            action_taken=response.action_taken,
            requires_followup=response.requires_followup
        )
