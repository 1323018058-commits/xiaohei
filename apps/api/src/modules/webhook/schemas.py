from pydantic import BaseModel


class TakealotWebhookAck(BaseModel):
    accepted: bool
    duplicate: bool
    task_id: str | None
    delivery_id: str
    event_type: str
