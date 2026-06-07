from typing import Optional, Dict, Any

class NullTokenStore:
    def save(self, user_id: str, data: dict):
        pass
        
    def load(self, user_id: str) -> Optional[dict]:
        return None

class SupabaseTokenStore:
    def __init__(self, supabase):
        self.supabase = supabase
        
    def save(self, user_id: str, data: dict):
        self.supabase.table("user_tokens").upsert({
            "user_id": user_id,
            "token_data": data
        }).execute()
        
    def load(self, user_id: str) -> Optional[dict]:
        response = self.supabase.table("user_tokens").select("token_data").eq("user_id", user_id).execute()
        if response.data:
            return response.data[0].get("token_data")
        return None
