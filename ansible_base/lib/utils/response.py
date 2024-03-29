import csv
from dataclasses import dataclass
from typing import Optional, Sequence

from django.http import StreamingHttpResponse


class CSVBuffer:
    """An object that implements just the write method of the file-like Protocol
    # NOTE: cannot use io.StringIO because its write returns length instead of text
    # we need the text to be immediatelly written to the streaming response.
    """

    def write(self, value):
        return value


@dataclass
class CSVStreamResponse:
    """Streams a CSV from any sequence e.g: queryset, generator"""

    lines: Sequence[Sequence[str]]  # can be a generator that yields tuple[str]
    filename: Optional[str] = None
    content_type: str = "text/event-stream"
    headers: Optional[dict] = None

    def stream(self):
        writer = csv.writer(CSVBuffer())
        headers = {"Cache-Control": "no-cache"} if self.headers is None else self.headers
        if self.filename:  # pragma: no cover
            headers["Content-Disposition"] = f"attachment; filename={self.filename}"

        return StreamingHttpResponse((writer.writerow(line) for line in self.lines), status=200, content_type=self.content_type, headers=headers)
