from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from datetime import datetime, timedelta
import os.path
import pickle
from tzlocal import get_localzone
import pytz
from typing import Dict, List, Optional, Any
import re

class CalendarManager:
    SCOPES = ['https://www.googleapis.com/auth/calendar']
    
    def __init__(self, auth_manager):
        self.auth_manager = auth_manager
        self.service = self._get_calendar_service()
        self.local_tz = get_localzone()
    
    def _get_calendar_service(self):
        """Get or create Google Calendar service"""
        creds = self.auth_manager.get_credentials()
        return build('calendar', 'v3', credentials=creds)
    
    def execute_command(self, intent: str, entities: Dict[str, Any]) -> str:
        """Execute calendar operation based on intent and entities"""
        try:
            if intent == "create_event":
                return self.create_event(entities)
            elif intent == "read_events":
                return self.read_events(entities)
            elif intent == "update_event":
                return self.update_event(entities)
            elif intent == "delete_event":
                return self.delete_event(entities)
            else:
                return "I'm not sure how to help with this calendar operation."
        except Exception as e:
            return f"Unexpected error occurred: {str(e)}"
    
    def _validate_datetime(self, datetime_str: str) -> Optional[datetime]:
        """Validate and parse datetime string"""
        if not datetime_str:
            return None
        
        try:
            # Handle different datetime formats
            if datetime_str.endswith('Z'):
                # UTC format
                dt = datetime.fromisoformat(datetime_str.replace('Z', '+00:00'))
                return dt.astimezone(self.local_tz)
            else:
                # ISO format with timezone
                dt = datetime.fromisoformat(datetime_str)
                if dt.tzinfo is None:
                    # Naive datetime - assume local timezone
                    dt = self.local_tz.localize(dt)
                return dt
        except (ValueError, TypeError) as e:
            print(f"Error parsing datetime '{datetime_str}': {e}")
            return None
    
    def _format_datetime_for_api(self, dt: datetime) -> str:
        """Format datetime for Google Calendar API"""
        if dt.tzinfo is None:
            dt = self.local_tz.localize(dt)
        return dt.isoformat()
    
    def _format_datetime_for_display(self, datetime_str: str) -> str:
        """Format datetime string for user-friendly display"""
        try:
            dt = self._validate_datetime(datetime_str)
            if dt:
                return dt.strftime('%A, %B %d, %Y at %I:%M %p')
            return datetime_str
        except:
            return datetime_str
    
    def create_event(self, entities: Dict[str, Any]) -> str:
        """Create a new calendar event with comprehensive validation"""
        
        # Validate required fields
        start_time_str = entities.get('start_time')
        end_time_str = entities.get('end_time')
        
        if not start_time_str or not end_time_str:
            return "Error: Both start time and end time are required to create an event."
        
        # Parse and validate times
        start_time = self._validate_datetime(start_time_str)
        end_time = self._validate_datetime(end_time_str)
        
        if not start_time or not end_time:
            return "Error: Invalid date/time format. Please provide valid start and end times."
        
        # Validate time logic
        if start_time >= end_time:
            return "Error: Start time must be before end time."
        
        # Check if event is in the past (with 5-minute buffer)
        now = datetime.now(self.local_tz)
        if start_time < (now - timedelta(minutes=5)):
            return "Warning: You're scheduling an event in the past. Please check your date and time."
        
        # Validate event duration (not too short or too long)
        duration = end_time - start_time
        if duration < timedelta(minutes=1):
            return "Error: Event duration must be at least 1 minute."
        if duration > timedelta(days=7):
            return "Warning: Event duration exceeds 7 days. Please verify your end time."
        
        try:
            # Check for conflicts
            conflict_check = self._check_for_conflicts(start_time, end_time)
            conflict_warning = ""
            if conflict_check:
                conflict_warning = f" (Note: This overlaps with existing event: {conflict_check})"
            
            # Create event object
            event = {
                'summary': entities.get('title', 'New Event').strip(),
                'start': {
                    'dateTime': self._format_datetime_for_api(start_time),
                    'timeZone': str(self.local_tz),
                },
                'end': {
                    'dateTime': self._format_datetime_for_api(end_time),
                    'timeZone': str(self.local_tz),
                },
            }
            
            # Add optional fields
            if entities.get('description'):
                event['description'] = entities['description'].strip()
            if entities.get('location'):
                event['location'] = entities['location'].strip()
            if entities.get('attendees'):
                event['attendees'] = [{'email': email.strip()} for email in entities['attendees']]
            
            # Create the event
            created_event = self.service.events().insert(calendarId='primary', body=event).execute()
            
            # Format response
            title = created_event.get('summary', 'Event')
            start_display = self._format_datetime_for_display(start_time_str)
            end_display = start_time.strftime('%I:%M %p') + " to " + end_time.strftime('%I:%M %p')
            
            return f"✅ Successfully created '{title}' on {start_display.split(' at ')[0]} from {end_display}{conflict_warning}"
        
        except HttpError as e:
            if e.resp.status == 409:
                return "Error: There's a conflict with an existing event. Please choose a different time."
            elif e.resp.status == 403:
                return "Error: Permission denied. Please check your calendar permissions."
            else:
                return f"Error creating event: {e.error_details if hasattr(e, 'error_details') else str(e)}"
        except Exception as e:
            return f"Error creating event: {str(e)}"
    
    def read_events(self, entities: Dict[str, Any]) -> str:
        """Read calendar events with flexible time range options"""
        try:
            # Determine time range
            start_time = entities.get('start_time')
            end_time = entities.get('end_time')
            
            # Default to next 7 days if no range specified
            if not start_time and not end_time:
                now = datetime.now(self.local_tz)
                start_time = now.isoformat()
                end_time = (now + timedelta(days=7)).isoformat()
            elif start_time and not end_time:
                # If only start time given, show events for that day
                start_dt = self._validate_datetime(start_time)
                if start_dt:
                    end_dt = start_dt.replace(hour=23, minute=59, second=59)
                    start_time = self._format_datetime_for_api(start_dt)
                    end_time = self._format_datetime_for_api(end_dt)
            
            # Query events
            events_result = self.service.events().list(
                calendarId='primary',
                timeMin=start_time,
                timeMax=end_time,
                singleEvents=True,
                orderBy='startTime',
                maxResults=50  # Limit results
            ).execute()
            
            events = events_result.get('items', [])
            
            if not events:
                time_range = self._get_time_range_description(start_time, end_time)
                return f"📅 No events found {time_range}."
            
            # Format response
            response = f"📅 Found {len(events)} event(s):\n\n"
            
            for i, event in enumerate(events, 1):
                title = event.get('summary', 'Untitled Event')
                start = event['start'].get('dateTime', event['start'].get('date'))
                end = event['end'].get('dateTime', event['end'].get('date'))
                
                # Format time display
                start_display = self._format_datetime_for_display(start)
                if end:
                    end_dt = self._validate_datetime(end)
                    if end_dt:
                        end_time_only = end_dt.strftime('%I:%M %p')
                        time_display = f"{start_display} - {end_time_only}"
                    else:
                        time_display = start_display
                else:
                    time_display = start_display
                
                response += f"{i}. {title}\n   📍 {time_display}\n"
                
                if event.get('location'):
                    response += f"   🏢 {event['location']}\n"
                
                response += "\n"
            
            return response.strip()
            
        except HttpError as e:
            return f"Error reading events: {str(e)}"
        except Exception as e:
            return f"Error reading events: {str(e)}"
    
    def update_event(self, entities: Dict[str, Any]) -> str:
        """Update an existing calendar event"""
        try:
            event_id = entities.get('event_id')
            event_title = entities.get('title')
            
            # If no event_id provided, try to find by title and date
            if not event_id and event_title:
                event_id = self._find_event_by_title_and_date(
                    event_title, 
                    entities.get('start_time'), 
                    entities.get('date')
                )
            
            if not event_id:
                return "Error: Could not identify which event to update. Please provide more specific information."
            
            # Get existing event
            try:
                event = self.service.events().get(calendarId='primary', eventId=event_id).execute()
            except HttpError as e:
                if e.resp.status == 404:
                    return "Error: Event not found. It may have been deleted or you don't have access."
                raise
            
            original_title = event.get('summary', 'Untitled Event')
            changes = []
            
            # Update event fields
            if 'title' in entities and entities['title'].strip():
                event['summary'] = entities['title'].strip()
                changes.append(f"title to '{entities['title']}'")
            
            if 'start_time' in entities:
                start_time = self._validate_datetime(entities['start_time'])
                if start_time:
                    event['start']['dateTime'] = self._format_datetime_for_api(start_time)
                    changes.append(f"start time to {self._format_datetime_for_display(entities['start_time'])}")
                    
                    # Adjust end time if only start time changed
                    if 'end_time' not in entities and 'end' in event:
                        original_end = self._validate_datetime(event['end']['dateTime'])
                        if original_end:
                            original_start = self._validate_datetime(event['start']['dateTime'])
                            if original_start:
                                duration = original_end - original_start
                                new_end = start_time + duration
                                event['end']['dateTime'] = self._format_datetime_for_api(new_end)
            
            if 'end_time' in entities:
                end_time = self._validate_datetime(entities['end_time'])
                if end_time:
                    event['end']['dateTime'] = self._format_datetime_for_api(end_time)
                    changes.append(f"end time to {self._format_datetime_for_display(entities['end_time'])}")
            
            if 'description' in entities:
                event['description'] = entities['description'].strip()
                changes.append("description")
            
            if 'location' in entities:
                event['location'] = entities['location'].strip()
                changes.append(f"location to '{entities['location']}'")
            
            if not changes:
                return "No changes specified. Please tell me what you want to update."
            
            # Validate updated times
            if 'start' in event and 'end' in event:
                start_dt = self._validate_datetime(event['start']['dateTime'])
                end_dt = self._validate_datetime(event['end']['dateTime'])
                if start_dt and end_dt and start_dt >= end_dt:
                    return "Error: Updated start time must be before end time."
            
            # Update the event
            updated_event = self.service.events().update(
                calendarId='primary',
                eventId=event_id,
                body=event
            ).execute()
            
            changes_text = ", ".join(changes)
            return f"✅ Successfully updated '{original_title}' - changed {changes_text}."
            
        except HttpError as e:
            return f"Error updating event: {str(e)}"
        except Exception as e:
            return f"Error updating event: {str(e)}"
    
    def delete_event(self, entities: Dict[str, Any]) -> str:
        """Delete calendar event(s) with multiple identification methods"""
        try:
            event_id = entities.get('event_id')
            event_title = entities.get('title')
            start_time = entities.get('start_time')
            end_time = entities.get('end_time')
            date = entities.get('date')
            
            # Method 1: Delete by event ID
            if event_id:
                return self._delete_by_id(event_id)
            
            # Method 2: Delete by title and optional date
            if event_title:
                return self._delete_by_title_and_date(event_title, start_time or date)
            
            # Method 3: Delete all events in time range
            if start_time and end_time:
                return self._delete_by_time_range(start_time, end_time)
            
            # Method 4: Delete all events on specific date
            if date or start_time:
                target_date = date or start_time
                return self._delete_by_date(target_date)
            
            return "Error: Please specify which event to delete by providing the event title, date, or time range."
            
        except Exception as e:
            return f"Error deleting event: {str(e)}"
    
    def _delete_by_id(self, event_id: str) -> str:
        """Delete event by ID"""
        try:
            # Get event details before deletion
            event = self.service.events().get(calendarId='primary', eventId=event_id).execute()
            title = event.get('summary', 'Untitled Event')
            
            self.service.events().delete(calendarId='primary', eventId=event_id).execute()
            return f"✅ Successfully deleted '{title}'."
        except HttpError as e:
            if e.resp.status == 404:
                return "Error: Event not found. It may have already been deleted."
            raise
    
    def _delete_by_title_and_date(self, title: str, date_str: str = None) -> str:
        """Delete event by title and optional date"""
        events = self._find_events_by_title(title, date_str)
        
        if not events:
            date_info = f" on {self._format_datetime_for_display(date_str).split(' at ')[0]}" if date_str else ""
            return f"No events found with title '{title}'{date_info}."
        
        if len(events) > 1:
            return f"Found {len(events)} events with title '{title}'. Please be more specific or provide a date."
        
        event = events[0]
        self.service.events().delete(calendarId='primary', eventId=event['id']).execute()
        return f"✅ Successfully deleted '{title}'."
    
    def _delete_by_time_range(self, start_time: str, end_time: str, confirm: bool = False, event_ids: List[str] = None) -> str:
        """Delete all events in time range, with optional confirmation step"""
        try:
            if event_ids is None:
                events_result = self.service.events().list(
                    calendarId='primary',
                    timeMin=start_time,
                    timeMax=end_time,
                    singleEvents=True,
                    orderBy='startTime'
                ).execute()
                events = events_result.get('items', [])
                event_ids = [event['id'] for event in events]
                event_titles = [event.get('summary', 'Untitled') for event in events]
            else:
                # If event_ids are provided, fetch event titles for confirmation message
                event_titles = []
                for event_id in event_ids:
                    try:
                        event = self.service.events().get(calendarId='primary', eventId=event_id).execute()
                        event_titles.append(event.get('summary', 'Untitled'))
                    except Exception:
                        event_titles.append('Untitled')

            if not event_ids:
                return "No events found in the specified time range."

            if not confirm:
                return f"Found {len(event_ids)} events to delete: {', '.join(event_titles)}. Please confirm if you want to delete all these events."

            # Confirmed: delete all events
            for event_id in event_ids:
                self.service.events().delete(calendarId='primary', eventId=event_id).execute()
            return f"✅ Successfully deleted {len(event_ids)} event(s)."
        except HttpError as e:
            return f"Error deleting events: {str(e)}"

    def get_pending_delete_event_ids(self, entities):
        """Get event IDs for pending delete confirmation (used by session/context)"""
        start_time = entities.get('start_time')
        end_time = entities.get('end_time')
        events_result = self.service.events().list(
            calendarId='primary',
            timeMin=start_time,
            timeMax=end_time,
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        events = events_result.get('items', [])
        return [event['id'] for event in events]

    def confirm_delete_events(self, event_ids):
        """Actually delete the events after user confirmation"""
        for event_id in event_ids:
            self.service.events().delete(calendarId='primary', eventId=event_id).execute()
        return f"✅ Successfully deleted {len(event_ids)} event(s)."
    
    def _delete_by_date(self, date_str: str) -> str:
        """Delete all events on a specific date"""
        target_date = self._validate_datetime(date_str)
        if not target_date:
            return "Error: Invalid date format."
        
        # Set time range for the entire day
        start_of_day = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = target_date.replace(hour=23, minute=59, second=59, microsecond=999999)
        
        return self._delete_by_time_range(
            self._format_datetime_for_api(start_of_day),
            self._format_datetime_for_api(end_of_day)
        )
    
    def _find_events_by_title(self, title: str, date_str: str = None) -> List[Dict]:
        """Find events by title and optional date"""
        try:
            # Set search time range
            if date_str:
                target_date = self._validate_datetime(date_str)
                if target_date:
                    start_time = target_date.replace(hour=0, minute=0, second=0)
                    end_time = target_date.replace(hour=23, minute=59, second=59)
                else:
                    # Default to next 30 days
                    now = datetime.now(self.local_tz)
                    start_time = now
                    end_time = now + timedelta(days=30)
            else:
                # Search next 30 days
                now = datetime.now(self.local_tz)
                start_time = now
                end_time = now + timedelta(days=30)
            
            events_result = self.service.events().list(
                calendarId='primary',
                timeMin=self._format_datetime_for_api(start_time),
                timeMax=self._format_datetime_for_api(end_time),
                singleEvents=True,
                q=title  # Use Google's search functionality
            ).execute()
            
            events = events_result.get('items', [])
            
            # Filter by exact title match (case insensitive)
            matching_events = []
            for event in events:
                event_title = event.get('summary', '').lower()
                if title.lower() in event_title:
                    matching_events.append(event)
            
            return matching_events
            
        except Exception as e:
            print(f"Error finding events: {e}")
            return []
    
    def _find_event_by_title_and_date(self, title: str, date_str: str = None, fallback_date: str = None) -> Optional[str]:
        """Find event ID by title and date"""
        search_date = date_str or fallback_date
        events = self._find_events_by_title(title, search_date)
        
        if len(events) == 1:
            return events[0]['id']
        
        return None
    
    def _check_for_conflicts(self, start_time: datetime, end_time: datetime) -> Optional[str]:
        """Check for conflicting events"""
        try:
            events_result = self.service.events().list(
                calendarId='primary',
                timeMin=self._format_datetime_for_api(start_time),
                timeMax=self._format_datetime_for_api(end_time),
                singleEvents=True
            ).execute()
            
            events = events_result.get('items', [])
            if events:
                return events[0].get('summary', 'Untitled Event')
            
            return None
        except:
            return None
    
    def _get_time_range_description(self, start_time: str, end_time: str) -> str:
        """Get human-readable description of time range"""
        try:
            start_dt = self._validate_datetime(start_time)
            end_dt = self._validate_datetime(end_time)
            
            if start_dt and end_dt:
                start_str = start_dt.strftime('%B %d, %Y')
                end_str = end_dt.strftime('%B %d, %Y')
                
                if start_str == end_str:
                    return f"on {start_str}"
                else:
                    return f"from {start_str} to {end_str}"
            
            return "in the specified time range"
        except:
            return "in the specified time range" 