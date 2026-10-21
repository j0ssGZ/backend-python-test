from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

from notification_service.domain import Channel, Status

router = APIRouter(prefix="/v1/requests")


class CreateRequest(BaseModel):
    to: str
    message: str
    type: Channel


class CreatedRequest(BaseModel):
    id: str


class RequestStatus(BaseModel):
    id: str
    status: Status


@router.post("", status_code=201, response_model=CreatedRequest)
async def create_request(body: CreateRequest, request: Request) -> CreatedRequest:
    notification = await request.app.state.service.create(body.to, body.message, body.type)
    return CreatedRequest(id=notification.id)


@router.post("/{request_id}/process", status_code=202, response_model=RequestStatus)
async def process_request(request_id: str, request: Request, response: Response) -> RequestStatus:
    notification = await request.app.state.service.process(request_id)
    if notification.status in (Status.SENT, Status.FAILED):
        response.status_code = 200
    return RequestStatus(id=notification.id, status=notification.status)


@router.get("/{request_id}", response_model=RequestStatus)
async def get_request(request_id: str, request: Request) -> RequestStatus:
    notification = await request.app.state.service.get(request_id)
    return RequestStatus(id=notification.id, status=notification.status)
