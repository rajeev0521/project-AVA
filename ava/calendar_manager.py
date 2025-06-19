from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from datetime import datetime, timedelta
import os.path
import pickle
from tzlocal import get_localzone

class CalendarManager:
    SCOPES = ['https://www.googleapis.com/auth/calendar']
    
    def __init__(self, auth_manager):
        self.auth_manager = auth_manager
        self.service = self._get_calendar_service()
    
    def _get_calendar_service(self):
        """Get or create Google Calendar service"""
        creds = self.auth_manager.get_credentials()
        return build('calendar', 'v3', credentials=creds)
    
    def execute_command(self, intent, entities):
        """Execute calendar operation based on intent and entities"""
        if intent == "create_event":
            return self.create_event(entities)
        elif intent == "read_events":
            return self.read_events(entities)
        elif intent == "update_event":
            return self.update_event(entities)
        elif intent == "delete_event":
            return self.delete_event(entities)
        else:
            return "I'm not sure how to help with that."
    
    def create_event(self, entities):
        """Create a new calendar event"""
        
        # Validate required fields
        if not entities.get('start_time') or not entities.get('end_time'):
            return "Start time and end time are required to create an event."
        if entities.get('start_time') >= entities.get('end_time'):
            return "Invalid! input time: Start time must be before end time."
        
        try:
            local_tz = get_localzone()
            event = {
                'summary': entities.get('title', 'New Event'),
                'start': {
                    'dateTime': entities.get('start_time'),
                    'timeZone': str(local_tz),
                },
                'end': {
                    'dateTime': entities.get('end_time'),
                    'timeZone': str(local_tz),
                },
            }
            
            event = self.service.events().insert(calendarId='primary', body=event).execute()
            return f"Event created: {event.get('htmlLink')}"
        
        except Exception as e:
            return f"Error creating event: {str(e)}"
    
    def read_events(self, entities):
        """Read calendar events for a given time period"""
        try:
            time_min = entities.get('start_time', datetime.utcnow().isoformat() + 'Z')
            time_max = entities.get('end_time', (datetime.utcnow() + timedelta(days=7)).isoformat() + 'Z')
            
            events_result = self.service.events().list(
                calendarId='primary',
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            
            events = events_result.get('items', [])
            if not events:
                return "No upcoming events found."
            
            response = "Here are your upcoming events:\n"
            for event in events:
                start = event['start'].get('dateTime', event['start'].get('date'))
                response += f"- {event['summary']} at {start}\n"
            
            return response
        except Exception as e:
            return f"Error reading events: {str(e)}"
    
    def update_event(self, entities):
        """Update an existing calendar event"""
        try:
            event_id = entities.get('event_id')
            if not event_id:
                return "Event ID is required for updating."
            
            event = self.service.events().get(calendarId='primary', eventId=event_id).execute()
            
            # Update event fields
            if 'title' in entities:
                event['summary'] = entities['title']
            if 'start_time' in entities:
                event['start']['dateTime'] = entities['start_time']
            if 'end_time' in entities:
                event['end']['dateTime'] = entities['end_time']
            
            updated_event = self.service.events().update(
                calendarId='primary',
                eventId=event_id,
                body=event
            ).execute()
            
            return f"Event updated: {updated_event.get('htmlLink')}"
        except Exception as e:
            return f"Error updating event: {str(e)}"
    
    def delete_event(self, entities):
        """Delete a calendar event"""
        try:
            event_id = entities.get('event_id')
            if not event_id:
                return "Event ID is required for deletion."
            
            self.service.events().delete(calendarId='primary', eventId=event_id).execute()
            return "Event deleted successfully."
        except Exception as e:
            return f"Error deleting event: {str(e)}" 