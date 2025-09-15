from app.twilio_client import send_content_message
from credentials import CONTENT_SID_RANGES, CONTENT_SID_HALVES

def send_ranges(to_number: str):
    variables = {}  # או מה שיש לך
    send_content_message(
        to=to_number,
        content_sid=CONTENT_SID_RANGES,
        variables=variables,
    )

def send_halves(to_number: str):
    variables = {}  # או מה שיש לך
    send_content_message(
        to=to_number,
        content_sid=CONTENT_SID_HALVES,
        variables=variables,
    )
