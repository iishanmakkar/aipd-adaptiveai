"""Schema definitions for browser agent actions and results."""
from uuid import uuid4

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any

class BrowserAction(BaseModel):
    """Action to perform on the browser."""
    action: str = Field(..., description="Navigate, click, fill, select, scroll, type, press, extract")
    selector: Optional[str] = Field(None, description="CSS selector for the element")
    url: Optional[str] = Field(None, description="URL to navigate to")
    value: Optional[str] = Field(None, description="Value to fill in a field")
    option: Optional[str] = Field(None, description="Dropdown option to select")
    direction: Optional[str] = Field("down", description="Scroll direction: down, up")
    amount: Optional[int] = Field(300, description="Scroll amount in pixels")
    
class AccessibilityQuery(BaseModel):
    """Query the accessibility tree."""
    action: str = Field(..., description="extract, query, filter")
    roles: Optional[List[str]] = Field(None, description="Filter by ARIA roles")
    states: Optional[Dict[str, bool]] = Field(None, description="Filter by ARIA states: {disabled: true}")
    selector: Optional[str] = Field(None, description="CSS selector to query")
    
class VLMAnalysis(BaseModel):
    """Vision/LLM analysis request."""
    action: str = Field(..., description="describe, analyze, extract")
    image_data: Optional[str] = Field(None, description="Base64-encoded screenshot")
    prompt: Optional[str] = Field(None, description="Custom prompt for VLM")
    context: Optional[str] = Field(None, description="Additional context")
    
class FormField(BaseModel):
    """Form field information."""
    field_id: str = Field(..., description="Unique identifier for the field")
    label: str = Field(..., description="Visible label or ARIA label")
    role: str = Field(..., description="ARIA role: textfield, combobox, etc.")
    type: str = Field(..., description="HTML input type: text, email, password, etc.")
    name: Optional[str] = Field(None, description="Name attribute")
    placeholder: Optional[str] = Field(None, description="Placeholder text")
    required: bool = Field(False, description="Whether the field is required")
    
class FormFillingAction(BaseModel):
    """Form filling action."""
    action: str = Field(..., description="discover, fill, repair, cache")
    fields: Optional[List[FormField]] = Field(None, description="Fields to fill")
    form_purpose: Optional[str] = Field(None, description="Purpose description for LLM guidance")
    pattern_name: Optional[str] = Field(None, description="Cached pattern name for replay")
    
class TaskResult(BaseModel):
    """Result of a browser task execution."""
    session_id: str
    status: str  # completed, error, partial
    steps_completed: int
    steps_failed: int
    narration: str
    completed_at: str
    details: Optional[Dict[str, Any]] = Field(None, description="Detailed step results")
    
class EpisodicMemoryEntry(BaseModel):
    """Stored episodic memory entry for workflow replay."""
    id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str
    timestamp: str
    tool: str
    action: str
    args_summary: str
    result: Dict[str, Any]
    success: bool