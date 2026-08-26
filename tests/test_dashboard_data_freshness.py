from datetime import datetime,timezone
from monitoring.dashboard import envelope
def test_dashboard_envelope_marks_unavailable_as_stale_with_timestamp():
    result=envelope({},quality="UNAVAILABLE",timestamp=datetime.now(timezone.utc));assert result["stale"] and result["timestamp"] and result["source"] and result["version"]
