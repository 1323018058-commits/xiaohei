from fastapi import APIRouter, Request

from .schemas import TakealotWebhookAck
from .service import TakealotWebhookService

router = APIRouter(tags=["webhooks"])
service = TakealotWebhookService()


@router.post("/api/webhooks/takealot", response_model=TakealotWebhookAck, include_in_schema=False)
@router.post("/api/v1/webhooks/takealot", response_model=TakealotWebhookAck)
async def receive_takealot_webhook(request: Request):
    body = await request.body()
    return service.receive(
        headers=request.headers,
        body=body,
        received_url=str(request.url),
    )
